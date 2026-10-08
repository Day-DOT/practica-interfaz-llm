"""
clasificador_hibrido.py
=======================
Clasificador híbrido de correos de incidentes: LLM (Ollama / llama3.2) + reglas
por palabras clave, con validación mediante Pydantic.

Flujo:
    1. Se pide al LLM una respuesta JSON estricta y se valida con ``IncidenteEsquema``.
    2. Siempre se calcula también una clasificación por reglas de palabras clave.
    3. Si el LLM falla (conexión, timeout, JSON inválido, esquema inválido) se usa
       únicamente la clasificación por reglas (fallback).
    4. Si ambos responden y discrepan, prevalece la prioridad más alta y se marca
       ``requiere_revision_humana = True``.

Uso::

    from clasificador_hibrido import clasificar_correo
    r = clasificar_correo("URGENTE: fuga de combustible en el camión ABC-123")
    print(r.model_dump())

Dependencias::

    pip install ollama pydantic
    ollama pull llama3.2
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

import config

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
# El modelo, host, timeout y reintentos se leen de ``config`` en cada llamada.
MAX_CARACTERES_CORREO: int = 8000

Categoria = Literal["Seguridad", "Documentación", "Logística", "Otro"]
Prioridad = Literal["Alta", "Media", "Baja"]

CATEGORIAS_VALIDAS: tuple[str, ...] = ("Seguridad", "Documentación", "Logística", "Otro")
PRIORIDADES_VALIDAS: tuple[str, ...] = ("Alta", "Media", "Baja")
ORDEN_PRIORIDAD: dict[str, int] = {"Baja": 0, "Media": 1, "Alta": 2}

# Placas tipo ABC-123 / AB-1234 / ABC123 e IDs tipo CAM-0042, ID-12345.
PATRON_ENTIDADES = re.compile(
    r"\b(?:[A-Z]{2,3}[- ]?\d{3,4}|(?:CAM|ID|TRK|CONT)[- ]?\d{2,8})\b",
    re.IGNORECASE,
)

# Palabras clave (sin tildes, minúsculas).
PALABRAS_PRIORIDAD_ALTA: tuple[str, ...] = (
    "urgente", "urgencia", "emergencia", "inmediato", "inmediatamente", "critico",
    "fuga", "derrame", "incendio", "explosion", "accidente", "robo", "asalto",
    "herido", "lesionado", "intoxicacion", "peligro",
)
PALABRAS_PRIORIDAD_MEDIA: tuple[str, ...] = (
    "retraso", "demora", "vencido", "vencida", "falta", "faltante", "pendiente",
    "averia", "falla", "sello roto", "discrepancia", "reclamo", "incompleto",
)
PALABRAS_CATEGORIA: dict[str, tuple[str, ...]] = {
    "Seguridad": (
        "seguridad", "fuga", "derrame", "incendio", "explosion", "robo", "asalto",
        "accidente", "herido", "lesionado", "sello", "intrusion", "peligro",
        "material peligroso", "intoxicacion", "alarma",
    ),
    "Documentación": (
        "documento", "documentacion", "certificado", "certificacion", "licencia",
        "permiso", "vencido", "vencida", "factura", "guia", "manifiesto", "poliza",
        "firma", "incompleto",
    ),
    "Logística": (
        "retraso", "demora", "entrega", "ruta", "carga", "descarga", "almacen",
        "bodega", "transporte", "despacho", "ubicacion", "muelle", "inventario",
        "averia", "faltante",
    ),
}


# --------------------------------------------------------------------------- #
# Modelo Pydantic
# --------------------------------------------------------------------------- #
def _sin_tildes(texto: str) -> str:
    """Minúsculas y sin diacríticos, para comparar palabras clave y normalizar salidas."""
    normal = unicodedata.normalize("NFD", texto)
    return "".join(c for c in normal if unicodedata.category(c) != "Mn").lower().strip()


class IncidenteEsquema(BaseModel):
    """Resultado estructurado de la clasificación de un correo de incidente."""

    categoria: Categoria = Field(description="Seguridad, Documentación, Logística u Otro")
    prioridad: Prioridad = Field(description="Alta, Media o Baja")
    entidades: list[str] = Field(default_factory=list, description="Placas o IDs mencionados")
    resumen: str = Field(min_length=1, max_length=500, description="Resumen breve del incidente")
    requiere_revision_humana: bool = False
    origen: Literal["llm", "reglas", "fusion"] = "llm"

    @field_validator("categoria", mode="before")
    @classmethod
    def _normalizar_categoria(cls, valor: Any) -> Any:
        """Tolera mayúsculas/minúsculas y tildes ('seguridad', 'DOCUMENTACION')."""
        if isinstance(valor, str):
            clave = _sin_tildes(valor)
            for oficial in CATEGORIAS_VALIDAS:
                if _sin_tildes(oficial) == clave:
                    return oficial
        return valor

    @field_validator("prioridad", mode="before")
    @classmethod
    def _normalizar_prioridad(cls, valor: Any) -> Any:
        """Tolera 'alta', 'ALTA', etc."""
        if isinstance(valor, str):
            clave = _sin_tildes(valor)
            for oficial in PRIORIDADES_VALIDAS:
                if _sin_tildes(oficial) == clave:
                    return oficial
        return valor

    @field_validator("entidades", mode="before")
    @classmethod
    def _normalizar_entidades(cls, valor: Any) -> Any:
        """Acepta ``None`` o un string suelto; elimina vacíos y duplicados."""
        if valor is None:
            return []
        if isinstance(valor, str):
            valor = [valor]
        if isinstance(valor, list):
            return _deduplicar([str(v).strip().upper() for v in valor if str(v).strip()])
        return valor

    @field_validator("resumen", mode="before")
    @classmethod
    def _recortar_resumen(cls, valor: Any) -> Any:
        """Recorta resúmenes demasiado largos en lugar de rechazarlos."""
        if isinstance(valor, str):
            valor = valor.strip()
            return valor[:500]
        return valor


def _deduplicar(items: list[str]) -> list[str]:
    """Elimina duplicados conservando el orden."""
    vistos: set[str] = set()
    salida: list[str] = []
    for item in items:
        if item not in vistos:
            vistos.add(item)
            salida.append(item)
    return salida


# --------------------------------------------------------------------------- #
# Errores
# --------------------------------------------------------------------------- #
class ErrorLLM(Exception):
    """Fallo al obtener o interpretar la respuesta del LLM.

    Attributes:
        recuperable: ``True`` si tiene sentido reintentar (respuesta mal formada);
            ``False`` si el servicio no está disponible (conexión, modelo, paquete).
        respuesta: Texto crudo devuelto por el modelo, si lo hubo.
    """

    def __init__(self, mensaje: str, recuperable: bool = False, respuesta: str = "") -> None:
        super().__init__(mensaje)
        self.recuperable = recuperable
        self.respuesta = respuesta


@dataclass
class IntentoLLM:
    """Registro de una llamada al LLM (para ``evaluaciones_llm``)."""

    prompt: str
    respuesta: str
    latencia_ms: float
    modelo: str
    error: Optional[str] = None

    @property
    def valido(self) -> bool:
        return self.error is None


@dataclass
class ResultadoClasificacion:
    """Resultado completo del clasificador híbrido, con trazabilidad."""

    final: IncidenteEsquema
    reglas: IncidenteEsquema
    llm: Optional[IncidenteEsquema]
    intentos: list[IntentoLLM] = field(default_factory=list)
    latencia_reglas_ms: float = 0.0
    latencia_total_ms: float = 0.0

    @property
    def coincide_con_reglas(self) -> Optional[bool]:
        """``True`` si el LLM coincide con las reglas en categoría y prioridad (``None`` sin LLM)."""
        if self.llm is None:
            return None
        return (self.llm.categoria, self.llm.prioridad) == (self.reglas.categoria, self.reglas.prioridad)


# --------------------------------------------------------------------------- #
# Clasificación por reglas (fallback / contraste)
# --------------------------------------------------------------------------- #
def extraer_entidades(texto: str) -> list[str]:
    """Extrae placas e IDs del texto mediante expresión regular."""
    encontradas = [m.group(0).upper().replace(" ", "-") for m in PATRON_ENTIDADES.finditer(texto)]
    return _deduplicar(encontradas)


def _contiene(texto_norm: str, palabras: tuple[str, ...]) -> list[str]:
    """Retorna las palabras clave presentes en el texto normalizado."""
    return [p for p in palabras if re.search(rf"\b{re.escape(p)}", texto_norm)]


def clasificar_por_reglas(correo: str) -> IncidenteEsquema:
    """Clasifica un correo usando únicamente palabras clave.

    Categoría: la que acumule más coincidencias (empate -> orden Seguridad,
    Documentación, Logística); sin coincidencias -> ``Otro``.
    Prioridad: Alta si hay palabras críticas, Media si hay palabras de incidencia
    o la categoría es Seguridad, Baja en caso contrario.
    """
    texto = _sin_tildes(correo)

    puntajes = {cat: len(_contiene(texto, palabras)) for cat, palabras in PALABRAS_CATEGORIA.items()}
    mejor_cat, mejor_puntaje = max(puntajes.items(), key=lambda kv: kv[1])
    categoria: Categoria = mejor_cat if mejor_puntaje > 0 else "Otro"  # type: ignore[assignment]

    if _contiene(texto, PALABRAS_PRIORIDAD_ALTA):
        prioridad: Prioridad = "Alta"
    elif _contiene(texto, PALABRAS_PRIORIDAD_MEDIA) or categoria == "Seguridad":
        prioridad = "Media"
    else:
        prioridad = "Baja"

    resumen = " ".join(correo.split())[:200] or "Sin contenido"
    return IncidenteEsquema(
        categoria=categoria,
        prioridad=prioridad,
        entidades=extraer_entidades(correo),
        resumen=resumen,
        origen="reglas",
    )


# --------------------------------------------------------------------------- #
# Clasificación con LLM
# --------------------------------------------------------------------------- #
PROMPT_SISTEMA: str = (
    "Eres un asistente que clasifica correos de incidentes de control de acceso y "
    "logística de camiones. Responde ÚNICAMENTE con un objeto JSON válido, sin texto "
    "adicional ni bloques de código. Los correos pueden tener faltas de ortografía o "
    "lenguaje informal: interpreta la intención."
)

PLANTILLA_PROMPT: str = """Analiza el siguiente correo y devuelve un JSON con EXACTAMENTE estas claves:
- "categoria": una de "Seguridad", "Documentación", "Logística", "Otro"
- "prioridad": una de "Alta", "Media", "Baja"
- "entidades": lista de strings con las placas de camiones o IDs mencionados (lista vacía si no hay)
- "resumen": texto breve (máximo 200 caracteres) del incidente

Criterios: Alta = riesgo para personas, carga o instalaciones, o el correo exige acción inmediata; \
Media = afecta la operación pero sin riesgo inmediato; Baja = informativo o sin impacto.
Usa "Otro" para correos que no tienen relación con seguridad, documentación o logística de camiones.

Ejemplo de salida:
{{"categoria": "Seguridad", "prioridad": "Alta", "entidades": ["ABC-123"], "resumen": "Fuga de combustible en camión ABC-123."}}

CORREO:
\"\"\"
{correo}
\"\"\"
"""

PLANTILLA_REINTENTO: str = (
    "Tu respuesta anterior no es válida ({motivo}). Responde de nuevo ÚNICAMENTE con el objeto "
    'JSON con las claves "categoria", "prioridad", "entidades" y "resumen".'
)


def _extraer_json(texto: str) -> dict[str, Any]:
    """Convierte la respuesta del LLM en dict, tolerando cercas ``` y texto alrededor.

    Raises:
        ErrorLLM: (recuperable) Si no se encuentra un objeto JSON válido.
    """
    limpio = texto.strip()
    limpio = re.sub(r"^```(?:json)?\s*|\s*```$", "", limpio, flags=re.IGNORECASE)
    try:
        datos = json.loads(limpio)
    except json.JSONDecodeError:
        inicio, fin = limpio.find("{"), limpio.rfind("}")
        if inicio == -1 or fin <= inicio:
            raise ErrorLLM("La respuesta del LLM no contiene un objeto JSON.", True, texto) from None
        try:
            datos = json.loads(limpio[inicio : fin + 1])
        except json.JSONDecodeError as exc:
            raise ErrorLLM(f"JSON inválido del LLM: {exc}", True, texto) from exc
    if not isinstance(datos, dict):
        raise ErrorLLM("El JSON del LLM no es un objeto.", True, texto)
    return datos


def _validar_respuesta(contenido: str) -> IncidenteEsquema:
    """Parsea y valida la respuesta cruda con Pydantic.

    Raises:
        ErrorLLM: (recuperable) Si está vacía, no es JSON o no cumple el esquema.
    """
    if not contenido or not contenido.strip():
        raise ErrorLLM("Ollama devolvió una respuesta vacía.", True, contenido or "")
    datos = _extraer_json(contenido)
    datos["origen"] = "llm"
    datos.pop("requiere_revision_humana", None)  # No se confía en este campo si viene del LLM.
    try:
        return IncidenteEsquema.model_validate(datos)
    except ValidationError as exc:
        raise ErrorLLM(f"La respuesta del LLM no cumple el esquema: {exc}", True, contenido) from exc


def _chat_ollama(mensajes: list[dict[str, str]], modelo: str) -> str:
    """Llama a Ollama y devuelve el texto de la respuesta.

    Raises:
        ErrorLLM: (no recuperable) Si falta el paquete, no hay conexión o el modelo falla.
    """
    try:
        import ollama  # Import diferido: si falta, se activa el fallback.
    except ImportError as exc:
        raise ErrorLLM("El paquete 'ollama' no está instalado (pip install ollama).") from exc
    try:
        cliente = ollama.Client(host=config.host_ollama(), timeout=config.get("timeout_ollama_s"))
        respuesta = cliente.chat(
            model=modelo, messages=mensajes, format="json",
            options={"temperature": 0, "num_ctx": 4096}
        )
        return respuesta["message"]["content"] or ""
    except Exception as exc:  # ollama/httpx lanzan varios tipos (conexión, timeout, modelo ausente)
        raise ErrorLLM(f"Fallo al consultar Ollama: {exc}") from exc


def consultar_llm(correo: str) -> tuple[Optional[IncidenteEsquema], list[IntentoLLM]]:
    """Clasifica con el LLM, reintentando si el JSON es inválido. Nunca lanza.

    Hace como máximo ``1 + reintentos_llm`` llamadas. Un error no recuperable (por
    ejemplo Ollama apagado) corta de inmediato.

    Returns:
        ``(resultado, intentos)``; ``resultado`` es ``None`` si todos los intentos fallaron.
    """
    modelo = config.get("modelo_ollama")
    prompt = PLANTILLA_PROMPT.format(correo=correo)
    mensajes: list[dict[str, str]] = [
        {"role": "system", "content": PROMPT_SISTEMA},
        {"role": "user", "content": prompt},
    ]
    intentos: list[IntentoLLM] = []

    for _ in range(1 + int(config.get("reintentos_llm"))):
        inicio = time.perf_counter()
        contenido = ""
        try:
            contenido = _chat_ollama(mensajes, modelo)
            resultado = _validar_respuesta(contenido)
        except ErrorLLM as exc:
            latencia = (time.perf_counter() - inicio) * 1000
            intentos.append(IntentoLLM(prompt, exc.respuesta or contenido, latencia, modelo, str(exc)))
            logger.warning("Intento LLM fallido (%s): %s", "recuperable" if exc.recuperable else "fatal", exc)
            if not exc.recuperable:
                return None, intentos
            mensajes = mensajes[:2] + [
                {"role": "assistant", "content": exc.respuesta},
                {"role": "user", "content": PLANTILLA_REINTENTO.format(motivo=str(exc)[:200])},
            ]
        else:
            latencia = (time.perf_counter() - inicio) * 1000
            intentos.append(IntentoLLM(prompt, contenido, latencia, modelo))
            return resultado, intentos
    return None, intentos


# --------------------------------------------------------------------------- #
# Fusión
# --------------------------------------------------------------------------- #
def fusionar(llm: IncidenteEsquema, reglas: IncidenteEsquema) -> IncidenteEsquema:
    """Combina la salida del LLM con la de las reglas.

    * Prioridad: prevalece la más alta.
    * Categoría: se conserva la del LLM; si discrepan y alguna dice ``Seguridad``
      prevalece ``Seguridad`` (ante la duda, seguridad); si el LLM dijo ``Otro`` y
      las reglas detectaron una categoría concreta, se usa la de las reglas.
    * Entidades: unión de ambas (el regex captura lo que el LLM omita).
    * ``requiere_revision_humana = True`` si categoría o prioridad discrepan.
    """
    discrepancia = (
        llm.prioridad != reglas.prioridad or llm.categoria != reglas.categoria
    )

    prioridad = max((llm.prioridad, reglas.prioridad), key=lambda p: ORDEN_PRIORIDAD[p])
    categoria = llm.categoria
    if llm.categoria != reglas.categoria:
        if "Seguridad" in (llm.categoria, reglas.categoria):
            categoria = "Seguridad"
        elif llm.categoria == "Otro":
            categoria = reglas.categoria

    return IncidenteEsquema(
        categoria=categoria,
        prioridad=prioridad,
        entidades=_deduplicar(llm.entidades + reglas.entidades),
        resumen=llm.resumen,
        requiere_revision_humana=discrepancia,
        origen="fusion",
    )


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #
def clasificar_correo_detallado(correo: str, usar_llm: bool = True) -> ResultadoClasificacion:
    """Clasifica un correo con el enfoque híbrido y devuelve toda la trazabilidad.

    Args:
        correo: Texto del correo (asunto + cuerpo).
        usar_llm: Si es ``False`` solo se usan las reglas.

    Returns:
        ``ResultadoClasificacion`` con el resultado final, la salida de reglas y de
        LLM por separado, los intentos al LLM y las latencias.

    Raises:
        ValueError: Si el correo es vacío o no es texto.
    """
    if not isinstance(correo, str) or not correo.strip():
        raise ValueError("El correo debe ser un texto no vacío.")
    correo = correo.strip()[:MAX_CARACTERES_CORREO]

    inicio = time.perf_counter()
    reglas = clasificar_por_reglas(correo)
    latencia_reglas = (time.perf_counter() - inicio) * 1000

    llm: Optional[IncidenteEsquema] = None
    intentos: list[IntentoLLM] = []
    if usar_llm:
        llm, intentos = consultar_llm(correo)

    if llm is None:
        if usar_llm:
            logger.warning("LLM no disponible, usando reglas (fallback).")
        if reglas.categoria == "Otro":
            reglas.requiere_revision_humana = True
        final = reglas
    else:
        final = fusionar(llm, reglas)

    return ResultadoClasificacion(
        final=final,
        reglas=reglas,
        llm=llm,
        intentos=intentos,
        latencia_reglas_ms=latencia_reglas,
        latencia_total_ms=(time.perf_counter() - inicio) * 1000,
    )
