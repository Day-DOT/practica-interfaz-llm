"""
asistente_rag.py
================
Asistente explicativo con patrón RAG sencillo (consulta primero, contexto después).

Flujo de ``consultar_asistente(consulta, db, historial)``:
    1. **Recuperación:** busca en ``accesos``, ``incidentes`` y ``camiones`` los registros
       más relevantes (coincidencia de placas/IDs y palabras clave, sin esquema fijo).
    2. **Contexto:** numera los registros recuperados [1], [2]...
    3. **Generación:** consulta a Ollama con un prompt estricto que solo permite usar el
       contexto y exige citar el registro de origen con [n].
    4. Si no hay registros relevantes, responde exactamente
       ``"No tengo información en los registros."`` sin llamar al LLM.
    5. Registra la llamada en ``evaluaciones_llm`` (prompt, respuesta, modelo, latencia).

Uso::

    from conexion import obtener_db
    from asistente_rag import consultar_asistente

    r = consultar_asistente("¿Por qué CAM-102 fue enviado a inspección?", obtener_db())
    print(r.respuesta, r.fuentes)

Dependencias::

    pip install ollama pymongo
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from bson import ObjectId
from pymongo.database import Database
from pymongo.errors import PyMongoError

import config

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
COLECCIONES_CONSULTA: tuple[str, ...] = ("accesos", "incidentes", "camiones")
MAX_DOCS_ESCANEO: int = 500       # Documentos más recientes a evaluar por colección.
MAX_REGISTROS_CONTEXTO: int = 4   # Registros enviados al LLM.
MAX_CARACTERES_REGISTRO: int = 600
MAX_CARACTERES_CONSULTA: int = 1000
TURNOS_HISTORIAL: int = 4         # Turnos previos (usuario/asistente) enviados al LLM.
CAMPOS_RUIDO: frozenset[str] = frozenset({"_id", "demo"})

#: Respuesta exacta cuando la información no está en los registros.
RESPUESTA_SIN_INFORMACION: str = "No tengo información en los registros."

PATRON_ENTIDADES = re.compile(
    r"\b(?:[A-Z]{2,3}[- ]?\d{3,4}|(?:CAM|ID|TRK|CONT)[- ]?\d{2,8})\b",
    re.IGNORECASE,
)

PALABRAS_VACIAS: frozenset[str] = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "y", "o",
    "en", "por", "para", "con", "sin", "que", "cual", "cuales", "como", "cuando", "donde",
    "quien", "es", "son", "fue", "fueron", "ha", "han", "hay", "se", "su", "sus", "lo",
    "me", "mi", "te", "tu", "a", "e", "u", "ese", "esa", "este", "esta", "todo", "todos",
    "dime", "dame", "muestra", "cuantos", "cuantas", "tiene", "tuvo", "tengo", "sobre",
    "informacion", "registro", "registros", "camion", "camiones", "porque", "pasa", "sabes", "saber",
    "puedes", "puede", "algo", "info",
})


class ErrorAsistenteRAG(Exception):
    """Fallo al consultar la base de datos o el LLM."""


@dataclass
class RespuestaRAG:
    """Respuesta del asistente con las fuentes consultadas."""

    respuesta: str
    fuentes: list[dict[str, Any]] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Recuperación
# --------------------------------------------------------------------------- #
def _normalizar(texto: str) -> str:
    """Minúsculas y sin tildes."""
    normal = unicodedata.normalize("NFD", texto)
    return "".join(c for c in normal if unicodedata.category(c) != "Mn").lower()


def _compacto(texto: str) -> str:
    """Normaliza y elimina guiones/espacios (para comparar placas 'ABC-123' = 'ABC123')."""
    return re.sub(r"[\s\-]", "", _normalizar(texto))


def _extraer_terminos(consulta: str) -> tuple[set[str], set[str]]:
    """Retorna ``(palabras_clave, entidades_compactas)`` de la consulta."""
    entidades = {_compacto(m.group(0)) for m in PATRON_ENTIDADES.finditer(consulta)}
    palabras = {
        p for p in re.findall(r"[a-z0-9]+", _normalizar(consulta))
        if len(p) >= 3 and p not in PALABRAS_VACIAS
    }
    return palabras, entidades


def _puntuar(doc_texto: str, palabras: set[str], entidades: set[str]) -> int:
    """Puntúa un documento: las entidades pesan 5, cada palabra clave 1."""
    texto_norm = _normalizar(doc_texto)
    texto_compacto = _compacto(doc_texto)
    puntaje = 5 * sum(1 for e in entidades if e in texto_compacto)
    puntaje += sum(1 for p in palabras if p in texto_norm)
    return puntaje


def _limpiar(valor: Any) -> Any:
    """Convierte fechas/ObjectId a texto y quita campos de ruido (recursivo)."""
    if isinstance(valor, dict):
        return {k: _limpiar(v) for k, v in valor.items() if k not in CAMPOS_RUIDO}
    if isinstance(valor, list):
        # Las explicaciones paso a paso se unen en un solo texto para ahorrar contexto.
        if valor and all(isinstance(x, str) for x in valor):
            return " ".join(" ".join(x.split()) for x in valor)
        return [_limpiar(x) for x in valor]
    if isinstance(valor, (datetime, date)):
        return valor.isoformat(timespec="minutes") if isinstance(valor, datetime) else valor.isoformat()
    if isinstance(valor, ObjectId):
        return str(valor)
    return valor


def _documento_a_texto(doc: dict[str, Any]) -> str:
    return json.dumps(_limpiar(doc), ensure_ascii=False, default=str)


def _si_no(valor: Any) -> str:
    return "sí" if valor else "no"


def _formatear_registro(coleccion: str, doc: dict[str, Any]) -> str:
    """Texto compacto y legible de un registro para el contexto del LLM.

    Un formato corto (en lugar del JSON completo) reduce los tokens enviados, lo que
    acelera la respuesta y evita que el modelo se pierda entre campos irrelevantes.
    """
    fecha = doc.get("fecha")
    fecha_txt = fecha.strftime("%Y-%m-%d %H:%M") if isinstance(fecha, datetime) else "?"
    if coleccion == "accesos" and "A" in doc:
        razones = [
            " ".join(linea.split()) for linea in doc.get("explicacion", [])
            if linea.strip().startswith(("Motivo", "Regla V activada", "Regla H activada", "Paso 6"))
        ]
        return (
            f"ACCESO {fecha_txt} | placa {doc.get('placa')} | camion_id {doc.get('camion_id') or '-'} | "
            f"operador {doc.get('operador')} | P={_si_no(doc.get('P'))} Q={_si_no(doc.get('Q'))} "
            f"R={_si_no(doc.get('R'))} S={_si_no(doc.get('S'))} | ingreso "
            f"{'AUTORIZADO' if doc.get('A') else 'DENEGADO'} | inspección "
            f"{'REQUERIDA' if doc.get('E') else 'no requerida'} | reglas extendidas: "
            f"{', '.join(doc.get('reglas_aplicadas', [])) or 'ninguna'} | explicación: {' '.join(razones)}"
        )
    if coleccion == "incidentes" and "clasificacion" in doc:
        c, d = doc["clasificacion"], doc.get("datos_extraidos", {})
        return (
            f"INCIDENTE {fecha_txt} | estado {doc.get('estado')} | categoría {c.get('categoria')} | "
            f"prioridad {c.get('prioridad')} | entidades {', '.join(d.get('entidades', [])) or '-'} | "
            f"resumen: {d.get('resumen')} | correo: {str(doc.get('correo', ''))[:200]}"
        )
    if coleccion == "camiones" and "placa" in doc:
        cert = doc.get("certificacion_conductor", {})
        vigencia = cert.get("vigencia")
        return (
            f"CAMIÓN placa {doc.get('placa')} | camion_id {doc.get('camion_id')} | empresa {doc.get('empresa')} | "
            f"autorizado {_si_no(doc.get('autorizacion'))} | conductor {cert.get('conductor') or '-'} | "
            f"certificación vence {vigencia.date().isoformat() if isinstance(vigencia, datetime) else '-'}"
        )
    return _documento_a_texto(doc)


def _etiqueta_fuente(coleccion: str, doc: dict[str, Any]) -> str:
    """Descripción corta de un registro para mostrar como fuente."""
    ref = doc.get("placa") or doc.get("camion_id") or ""
    fecha = doc.get("fecha") or doc.get("ultimo_acceso")
    fecha_txt = fecha.strftime("%Y-%m-%d %H:%M") if isinstance(fecha, datetime) else ""
    if coleccion == "incidentes":
        ref = ref or ", ".join(doc.get("datos_extraidos", {}).get("entidades", []))
    return " ".join(p for p in (coleccion, str(ref), fecha_txt) if p)


def recuperar_registros(
    consulta: str, db: Database, contexto_previo: str = ""
) -> list[dict[str, Any]]:
    """Recupera los registros más relevantes de las colecciones consultables.

    Args:
        consulta: Pregunta actual.
        db: Base de datos.
        contexto_previo: Texto de preguntas anteriores; sus placas/IDs se usan solo si la
            consulta actual no menciona ninguna (preguntas de seguimiento).

    Returns:
        Lista (por relevancia) de dicts con ``coleccion``, ``id``, ``etiqueta`` y ``texto``.

    Raises:
        ErrorAsistenteRAG: Si falla la lectura de MongoDB.
    """
    palabras, entidades = _extraer_terminos(consulta)
    if not entidades and contexto_previo:
        entidades = _extraer_terminos(contexto_previo)[1]
    if not palabras and not entidades:
        return []

    candidatos: list[tuple[int, str, dict[str, Any]]] = []
    try:
        for nombre in COLECCIONES_CONSULTA:
            for doc in db[nombre].find().sort("_id", -1).limit(MAX_DOCS_ESCANEO):
                puntaje = _puntuar(_documento_a_texto(doc), palabras, entidades)
                if puntaje > 0:
                    candidatos.append((puntaje, nombre, doc))
    except PyMongoError as exc:
        raise ErrorAsistenteRAG(f"Error al consultar MongoDB: {exc}") from exc

    # A igual puntaje prevalece el registro más reciente.
    candidatos.sort(key=lambda c: (c[0], c[2].get("fecha") or c[2].get("ultimo_acceso") or datetime.min),
                    reverse=True)
    return [
        {
            "coleccion": nombre,
            "id": str(doc["_id"]),
            "etiqueta": _etiqueta_fuente(nombre, doc),
            "texto": _formatear_registro(nombre, doc)[:MAX_CARACTERES_REGISTRO],
        }
        for _, nombre, doc in candidatos[:MAX_REGISTROS_CONTEXTO]
    ]


# --------------------------------------------------------------------------- #
# Generación
# --------------------------------------------------------------------------- #
PROMPT_SISTEMA: str = (
    "Eres un asistente de control de acceso y logística. Respondes en español usando SOLO los "
    "registros del CONTEXTO, que provienen de la base de datos. No uses conocimiento externo ni "
    "inventes datos (placas, fechas, nombres, cifras). Cita el registro de origen de cada dato con "
    "su número entre corchetes, por ejemplo [1]. Si el CONTEXTO no contiene nada relacionado con la "
    f'pregunta, responde exactamente: "{RESPUESTA_SIN_INFORMACION}"'
)

PLANTILLA_USUARIO: str = """CONTEXTO (registros de MongoDB):
{contexto}

PREGUNTA: {consulta}

RESPUESTA (breve, citando [n]):"""


def _construir_contexto(registros: list[dict[str, Any]]) -> str:
    """Formatea los registros recuperados como bloques numerados."""
    return "\n".join(
        f"[{i}] ({r['coleccion']}) {r['texto']}" for i, r in enumerate(registros, start=1)
    )


def _es_sin_informacion(respuesta: str) -> bool:
    """Detecta variantes de 'no tengo información' para devolver la frase exacta."""
    base = _normalizar(respuesta).strip(" .\n\"'")
    return base.startswith("no tengo informacion")


def _registrar_evaluacion(db: Database, prompt: str, respuesta: str, modelo: str,
                          latencia_ms: float, error: Optional[str]) -> None:
    """Guarda la llamada en ``evaluaciones_llm``; un fallo aquí no afecta a la respuesta."""
    try:
        import repositorio  # import diferido: evita dependencia circular al cargar módulos
        repositorio.registrar_evaluacion_llm(
            db, tipo="rag", prompt=prompt, respuesta=respuesta, modelo=modelo,
            latencia_ms=latencia_ms, coincide_con_reglas=None, error=error,
        )
    except Exception as exc:  # pragma: no cover - solo registro
        logger.warning("No se pudo registrar la evaluación RAG: %s", exc)


def consultar_asistente(
    consulta: str,
    db: Database,
    historial: Optional[list[dict[str, str]]] = None,
) -> RespuestaRAG:
    """Responde una consulta usando únicamente registros de MongoDB como fuente.

    Args:
        consulta: Pregunta del usuario en lenguaje natural.
        db: Base de datos devuelta por ``conexion.obtener_db()``.
        historial: Turnos previos ``[{"role": "user"|"assistant", "content": ...}]``.

    Returns:
        ``RespuestaRAG``. Si no hay datos relevantes, ``respuesta`` es exactamente
        ``"No tengo información en los registros."``.

    Raises:
        ValueError: Si la consulta está vacía.
        ErrorAsistenteRAG: Si falla MongoDB u Ollama.
    """
    if not isinstance(consulta, str) or not consulta.strip():
        raise ValueError("La consulta debe ser un texto no vacío.")
    consulta = consulta.strip()[:MAX_CARACTERES_CONSULTA]
    historial = historial or []

    previo = " ".join(t["content"] for t in historial if t.get("role") == "user")
    registros = recuperar_registros(consulta, db, previo)
    if not registros:
        logger.info("Sin registros relevantes; no se consulta al LLM.")
        return RespuestaRAG(RESPUESTA_SIN_INFORMACION)

    try:
        import ollama
    except ImportError as exc:
        raise ErrorAsistenteRAG("El paquete 'ollama' no está instalado (pip install ollama).") from exc

    modelo = config.get("modelo_ollama")
    usuario = PLANTILLA_USUARIO.format(contexto=_construir_contexto(registros), consulta=consulta)
    mensajes: list[dict[str, str]] = [{"role": "system", "content": PROMPT_SISTEMA}]
    mensajes += [
        {"role": t["role"], "content": t["content"]}
        for t in historial[-2 * TURNOS_HISTORIAL:] if t.get("role") in ("user", "assistant")
    ]
    mensajes.append({"role": "user", "content": usuario})

    inicio = time.perf_counter()
    try:
        cliente = ollama.Client(host=config.host_ollama(), timeout=config.get("timeout_ollama_s"))
        respuesta = cliente.chat(model=modelo, messages=mensajes,
                                 options={"temperature": 0, "num_ctx": 4096})
        texto = (respuesta["message"]["content"] or "").strip()
    except Exception as exc:  # ollama/httpx lanzan varios tipos de error
        latencia = (time.perf_counter() - inicio) * 1000
        _registrar_evaluacion(db, usuario, "", modelo, latencia, str(exc))
        raise ErrorAsistenteRAG(f"Fallo al consultar Ollama: {exc}") from exc
    latencia = (time.perf_counter() - inicio) * 1000
    _registrar_evaluacion(db, usuario, texto, modelo, latencia, None)

    if not texto or _es_sin_informacion(texto):
        return RespuestaRAG(RESPUESTA_SIN_INFORMACION)

    citadas = {int(n) for n in re.findall(r"\[(\d+)\]", texto)}
    fuentes = [
        {"n": i, "coleccion": r["coleccion"], "id": r["id"], "etiqueta": r["etiqueta"],
         "citada": i in citadas}
        for i, r in enumerate(registros, start=1)
    ]
    return RespuestaRAG(texto, fuentes)
