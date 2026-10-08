"""
config.py
=========
Configuración persistente de la aplicación (capa de configuración).

Los valores se guardan en ``config.json`` junto al código y se leen en tiempo de
ejecución, de modo que un cambio hecho desde la pestaña *Configuración* de la GUI
afecta de inmediato al clasificador, al asistente RAG y al motor de reglas.

Uso::

    import config
    modelo = config.get("modelo_ollama")
    config.actualizar(modelo_ollama="llama3.2", umbral_riesgo_alto=15)
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RUTA_CONFIG: Path = Path(__file__).with_name("config.json")

#: Valores por defecto; también definen el tipo esperado de cada clave.
DEFECTOS: dict[str, Any] = {
    "modelo_ollama": "llama3.2",
    "host_ollama": "",                # vacío -> http://localhost:11434
    "timeout_ollama_s": 240.0,
    "reintentos_llm": 1,              # reintentos ante JSON inválido (antes de caer a reglas)
    "umbral_riesgo_alto": 15,         # puntaje (prob x impacto) a partir del cual es crítico
    "umbral_riesgo_medio": 8,
    "modo_simulacion_correo": False,  # ofrece correos de ejemplo en la bandeja de incidentes
    "operador": "operador1",
    "horario_peligrosos_inicio": "06:00",
    "horario_peligrosos_fin": "18:00",
}

_candado = threading.Lock()
_valores: dict[str, Any] = dict(DEFECTOS)
_cargado = False


def _cargar_si_hace_falta() -> None:
    """Lee ``config.json`` la primera vez que se necesita (tolerando archivos dañados)."""
    global _cargado
    if _cargado:
        return
    _cargado = True
    if not RUTA_CONFIG.exists():
        return
    try:
        guardado = json.loads(RUTA_CONFIG.read_text(encoding="utf-8"))
        for clave, valor in guardado.items():
            if clave in DEFECTOS:
                _valores[clave] = _convertir(clave, valor)
    except (OSError, ValueError) as exc:
        logger.warning("No se pudo leer %s, se usan los valores por defecto: %s", RUTA_CONFIG, exc)


def _convertir(clave: str, valor: Any) -> Any:
    """Convierte ``valor`` al tipo del valor por defecto de ``clave``.

    Raises:
        ValueError: Si no se puede convertir.
    """
    defecto = DEFECTOS[clave]
    if isinstance(defecto, bool):
        if isinstance(valor, str):
            return valor.strip().lower() in {"1", "true", "si", "sí", "yes"}
        return bool(valor)
    if isinstance(defecto, int):
        return int(valor)
    if isinstance(defecto, float):
        return float(valor)
    return str(valor).strip()


def _hora(texto: str) -> time:
    return datetime.strptime(texto, "%H:%M").time()


def _validar(valores: dict[str, Any]) -> None:
    """Reglas de coherencia entre valores.

    Raises:
        ValueError: Con un mensaje claro para el usuario.
    """
    if not valores["modelo_ollama"]:
        raise ValueError("El modelo de Ollama no puede estar vacío.")
    if valores["timeout_ollama_s"] <= 0:
        raise ValueError("El tiempo de espera de Ollama debe ser mayor que 0.")
    if not 0 <= valores["reintentos_llm"] <= 5:
        raise ValueError("Los reintentos del LLM deben estar entre 0 y 5.")
    if not 1 <= valores["umbral_riesgo_medio"] < valores["umbral_riesgo_alto"] <= 25:
        raise ValueError("Los umbrales deben cumplir 1 <= medio < alto <= 25.")
    if not valores["operador"]:
        raise ValueError("El nombre del operador no puede estar vacío.")
    for clave in ("horario_peligrosos_inicio", "horario_peligrosos_fin"):
        try:
            _hora(valores[clave])
        except ValueError:
            raise ValueError("Los horarios deben tener el formato HH:MM (24 horas).") from None


def get(clave: str) -> Any:
    """Devuelve el valor actual de ``clave``."""
    with _candado:
        _cargar_si_hace_falta()
        return _valores[clave]


def todo() -> dict[str, Any]:
    """Copia de toda la configuración vigente."""
    with _candado:
        _cargar_si_hace_falta()
        return dict(_valores)


def actualizar(**cambios: Any) -> None:
    """Valida, aplica y guarda los cambios.

    Raises:
        ValueError: Si una clave no existe, un valor no es convertible o la
            combinación resultante es incoherente (no se aplica nada).
    """
    with _candado:
        _cargar_si_hace_falta()
        nuevos = dict(_valores)
        for clave, valor in cambios.items():
            if clave not in DEFECTOS:
                raise ValueError(f"Configuración desconocida: {clave}")
            try:
                nuevos[clave] = _convertir(clave, valor)
            except (TypeError, ValueError):
                raise ValueError(f"Valor inválido para '{clave}': {valor!r}") from None
        _validar(nuevos)
        _valores.update(nuevos)
        try:
            RUTA_CONFIG.write_text(json.dumps(_valores, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"No se pudo guardar config.json: {exc}") from exc


def restaurar_defectos() -> None:
    """Vuelve a los valores por defecto y los guarda."""
    actualizar(**DEFECTOS)


def horario_peligrosos() -> tuple[time, time]:
    """Horario permitido (inicio, fin) para materiales peligrosos."""
    return _hora(get("horario_peligrosos_inicio")), _hora(get("horario_peligrosos_fin"))


def host_ollama() -> str | None:
    """Host de Ollama o ``None`` para el valor por defecto."""
    return get("host_ollama") or None
