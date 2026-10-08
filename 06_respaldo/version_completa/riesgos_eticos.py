"""
riesgos_eticos.py
=================
Gestión y visualización de la matriz de riesgos éticos del sistema.

Cada riesgo guarda su valoración *inherente* (antes de mitigar) y *residual*
(después de aplicar la mitigación), más un histórico de cambios.

Esquema del documento (colección ``riesgos_eticos``)::

    {
      "modulo": "Asistente RAG",            # módulo del sistema afectado
      "nombre": "Alucinaciones del LLM",
      "descripcion": "...",
      "categoria": "Fiabilidad",            # Fiabilidad | Sesgo | Privacidad | Autonomía | Seguridad
      "probabilidad": 4, "impacto": 4,      # escala 1-5 (antes de la mitigación)
      "mitigacion": "...",
      "probabilidad_residual": 2, "impacto_residual": 4,   # después de la mitigación
      "historico": [{"fecha": ..., "probabilidad": ..., "impacto": ...,
                     "probabilidad_residual": ..., "impacto_residual": ..., "mitigacion": ...}],
      "fecha_creacion": ..., "fecha_actualizacion": ...
    }

Puntaje = probabilidad × impacto (1-25). Los umbrales viven en ``config``.

Funciones: ``obtener_riesgos`` (siembra si está vacía), ``crear_riesgo``,
``actualizar_riesgo``, ``eliminar_riesgo`` y ``crear_figura_matriz``.

Dependencias::

    pip install matplotlib pymongo
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from pymongo.database import Database
from pymongo.errors import PyMongoError

import config

logger = logging.getLogger(__name__)

NOMBRE_COLECCION: str = "riesgos_eticos"
CATEGORIAS: tuple[str, ...] = ("Fiabilidad", "Sesgo", "Privacidad", "Autonomía", "Seguridad")
MODULOS: tuple[str, ...] = (
    "Clasificador híbrido", "Asistente RAG", "Motor de reglas", "Base de datos", "Interfaz", "General",
)

#: Riesgos iniciales: los 4 exigidos por la práctica más dos propios de la implementación.
RIESGOS_SEMILLA: list[dict[str, Any]] = [
    {
        "modulo": "Asistente RAG",
        "nombre": "Alucinaciones del LLM",
        "descripcion": "El modelo inventa placas, fechas o hechos que no existen en los registros.",
        "categoria": "Fiabilidad",
        "probabilidad": 4, "impacto": 4,
        "mitigacion": "RAG con contexto estricto, respuesta fija 'No tengo información', citas [n] "
                      "de la fuente y revisión humana.",
        "probabilidad_residual": 2, "impacto_residual": 4,
    },
    {
        "modulo": "Clasificador híbrido",
        "nombre": "Sesgo por ortografía informal",
        "descripcion": "Correos con faltas de ortografía, abreviaturas o lenguaje informal se "
                       "clasifican peor que los correos formales.",
        "categoria": "Sesgo",
        "probabilidad": 4, "impacto": 3,
        "mitigacion": "Prompt que pide interpretar la intención, fusión con reglas (ante la duda, "
                      "seguridad) y revisión humana de discrepancias.",
        "probabilidad_residual": 3, "impacto_residual": 2,
    },
    {
        "modulo": "Base de datos",
        "nombre": "Privacidad de datos del conductor",
        "descripcion": "Exposición de datos personales del conductor (nombre, certificación) en "
                       "prompts, logs, reportes o clústeres compartidos.",
        "categoria": "Privacidad",
        "probabilidad": 3, "impacto": 5,
        "mitigacion": "LLM local (Ollama, sin enviar datos a terceros), minimización de datos, "
                      ".env fuera de Git y control de acceso al clúster.",
        "probabilidad_residual": 2, "impacto_residual": 3,
    },
    {
        "modulo": "General",
        "nombre": "Dependencia excesiva de la automatización",
        "descripcion": "El personal confía ciegamente en la decisión automática y deja de aplicar "
                       "su criterio.",
        "categoria": "Autonomía",
        "probabilidad": 4, "impacto": 4,
        "mitigacion": "Explicación paso a paso de cada decisión, marca requiere_revision_humana "
                      "y operador siempre registrado en la bitácora.",
        "probabilidad_residual": 3, "impacto_residual": 3,
    },
    {
        "modulo": "Motor de reglas",
        "nombre": "Reglas rígidas que bloquean casos legítimos",
        "descripcion": "Reglas conservadoras (p. ej. certificación sin fecha = vencida) pueden "
                       "negar ingresos válidos y generar fricción.",
        "categoria": "Seguridad",
        "probabilidad": 3, "impacto": 3,
        "mitigacion": "Tablas de verdad revisables, análisis de redundancias y proceso de "
                      "excepción con inspección manual.",
        "probabilidad_residual": 2, "impacto_residual": 2,
    },
    {
        "modulo": "Clasificador híbrido",
        "nombre": "Prioridad subestimada en incidentes de seguridad",
        "descripcion": "Un incidente real de seguridad se clasifica con prioridad baja y se "
                       "atiende tarde.",
        "categoria": "Seguridad",
        "probabilidad": 3, "impacto": 5,
        "mitigacion": "Fusión que prevalece la prioridad más alta y la categoría Seguridad ante "
                      "la duda; medición de exactitud en conjunto etiquetado.",
        "probabilidad_residual": 2, "impacto_residual": 4,
    },
]

COLOR_BAJO, COLOR_MEDIO, COLOR_ALTO = "#2e9e5b", "#e6a117", "#d64545"


class ErrorRiesgosEticos(Exception):
    """Fallo al leer/escribir riesgos o al generar la gráfica."""


# --------------------------------------------------------------------------- #
# Puntaje y validación
# --------------------------------------------------------------------------- #
def puntaje(probabilidad: float, impacto: float) -> float:
    """Puntaje de riesgo = probabilidad × impacto."""
    return probabilidad * impacto


def nivel(valor: float) -> str:
    """Clasifica un puntaje como ``Alto``, ``Medio`` o ``Bajo`` según los umbrales de ``config``."""
    if valor >= config.get("umbral_riesgo_alto"):
        return "Alto"
    if valor >= config.get("umbral_riesgo_medio"):
        return "Medio"
    return "Bajo"


def _color(valor: float) -> str:
    return {"Alto": COLOR_ALTO, "Medio": COLOR_MEDIO, "Bajo": COLOR_BAJO}[nivel(valor)]


def _entero_1_5(valor: Any, campo: str) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"'{campo}' debe ser un número entero entre 1 y 5.") from None
    if not 1 <= n <= 5:
        raise ValueError(f"'{campo}' debe estar entre 1 y 5.")
    return n


def validar_riesgo(datos: dict[str, Any]) -> dict[str, Any]:
    """Valida y normaliza los datos de un riesgo.

    Si faltan los valores residuales se asumen iguales a los inherentes (sin mitigación).

    Raises:
        ValueError: Con un mensaje claro si algún campo es inválido.
    """
    nombre = str(datos.get("nombre", "")).strip()
    if not nombre:
        raise ValueError("El nombre del riesgo es obligatorio.")
    descripcion = str(datos.get("descripcion", "")).strip()
    if not descripcion:
        raise ValueError("La descripción del riesgo es obligatoria.")
    categoria = str(datos.get("categoria", "")).strip() or "Fiabilidad"
    modulo = str(datos.get("modulo", "")).strip() or "General"

    prob = _entero_1_5(datos.get("probabilidad"), "Probabilidad")
    imp = _entero_1_5(datos.get("impacto"), "Impacto")
    prob_r = _entero_1_5(datos.get("probabilidad_residual", prob), "Probabilidad residual")
    imp_r = _entero_1_5(datos.get("impacto_residual", imp), "Impacto residual")
    if puntaje(prob_r, imp_r) > puntaje(prob, imp):
        raise ValueError("El riesgo residual no puede ser mayor que el riesgo inherente.")

    return {
        "modulo": modulo, "nombre": nombre, "descripcion": descripcion, "categoria": categoria,
        "probabilidad": prob, "impacto": imp,
        "mitigacion": str(datos.get("mitigacion", "")).strip(),
        "probabilidad_residual": prob_r, "impacto_residual": imp_r,
    }


def _a_object_id(valor: Any) -> ObjectId:
    try:
        return ObjectId(str(valor))
    except (InvalidId, TypeError):
        raise ErrorRiesgosEticos("Identificador de riesgo inválido.") from None


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
def _snapshot(doc: dict[str, Any], fecha: datetime) -> dict[str, Any]:
    return {
        "fecha": fecha,
        "probabilidad": doc["probabilidad"], "impacto": doc["impacto"],
        "probabilidad_residual": doc["probabilidad_residual"], "impacto_residual": doc["impacto_residual"],
        "mitigacion": doc.get("mitigacion", ""),
    }


def obtener_riesgos(db: Database) -> list[dict[str, Any]]:
    """Retorna los riesgos éticos; si la colección está vacía inserta la semilla.

    Raises:
        ErrorRiesgosEticos: Si falla la operación en MongoDB.
    """
    try:
        coleccion = db[NOMBRE_COLECCION]
        if coleccion.count_documents({}) == 0:
            ahora = datetime.now()
            docs = []
            for r in RIESGOS_SEMILLA:
                doc = dict(r)
                doc.update(fecha_creacion=ahora, fecha_actualizacion=ahora, historico=[_snapshot(doc, ahora)])
                docs.append(doc)
            coleccion.insert_many(docs)
            logger.info("Colección '%s' vacía: se insertaron %d riesgos semilla.", NOMBRE_COLECCION, len(docs))
        return list(coleccion.find().sort("_id", 1))
    except PyMongoError as exc:
        raise ErrorRiesgosEticos(f"Error al acceder a '{NOMBRE_COLECCION}': {exc}") from exc


def crear_riesgo(db: Database, datos: dict[str, Any]) -> str:
    """Valida e inserta un riesgo. Retorna su id.

    Raises:
        ValueError: Si los datos son inválidos.
        ErrorRiesgosEticos: Si falla MongoDB.
    """
    doc = validar_riesgo(datos)
    ahora = datetime.now()
    doc.update(fecha_creacion=ahora, fecha_actualizacion=ahora, historico=[_snapshot(doc, ahora)])
    try:
        return str(db[NOMBRE_COLECCION].insert_one(doc).inserted_id)
    except PyMongoError as exc:
        raise ErrorRiesgosEticos(f"No se pudo crear el riesgo: {exc}") from exc


def actualizar_riesgo(db: Database, riesgo_id: str, datos: dict[str, Any]) -> None:
    """Valida y actualiza un riesgo, añadiendo una entrada al histórico.

    Raises:
        ValueError: Si los datos son inválidos.
        ErrorRiesgosEticos: Si el riesgo no existe o falla MongoDB.
    """
    cambios = validar_riesgo(datos)
    ahora = datetime.now()
    try:
        res = db[NOMBRE_COLECCION].update_one(
            {"_id": _a_object_id(riesgo_id)},
            {"$set": {**cambios, "fecha_actualizacion": ahora},
             "$push": {"historico": _snapshot(cambios, ahora)}},
        )
    except PyMongoError as exc:
        raise ErrorRiesgosEticos(f"No se pudo actualizar el riesgo: {exc}") from exc
    if res.matched_count == 0:
        raise ErrorRiesgosEticos("El riesgo ya no existe.")


def eliminar_riesgo(db: Database, riesgo_id: str) -> None:
    """Elimina un riesgo.

    Raises:
        ErrorRiesgosEticos: Si no existe o falla MongoDB.
    """
    try:
        res = db[NOMBRE_COLECCION].delete_one({"_id": _a_object_id(riesgo_id)})
    except PyMongoError as exc:
        raise ErrorRiesgosEticos(f"No se pudo eliminar el riesgo: {exc}") from exc
    if res.deleted_count == 0:
        raise ErrorRiesgosEticos("El riesgo ya no existe.")


def contar_criticos(riesgos: list[dict[str, Any]]) -> tuple[int, int]:
    """Retorna ``(criticos_inherentes, criticos_residuales)`` según el umbral alto."""
    alto = config.get("umbral_riesgo_alto")
    inherentes = residuales = 0
    for r in riesgos:
        try:
            if puntaje(r["probabilidad"], r["impacto"]) >= alto:
                inherentes += 1
            if puntaje(r.get("probabilidad_residual", r["probabilidad"]),
                       r.get("impacto_residual", r["impacto"])) >= alto:
                residuales += 1
        except (KeyError, TypeError):
            continue
    return inherentes, residuales


# --------------------------------------------------------------------------- #
# Gráfica
# --------------------------------------------------------------------------- #
def _validos(riesgos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filtra riesgos con valores numéricos 1-5 válidos; registra los omitidos."""
    validos: list[dict[str, Any]] = []
    for r in riesgos:
        try:
            p, i = float(r["probabilidad"]), float(r["impacto"])
            pr = float(r.get("probabilidad_residual", p))
            ir = float(r.get("impacto_residual", i))
            nombre = str(r["nombre"])
        except (KeyError, TypeError, ValueError):
            logger.warning("Riesgo omitido por datos inválidos: %s", r.get("_id", r))
            continue
        if not all(1 <= v <= 5 for v in (p, i, pr, ir)):
            logger.warning("Riesgo '%s' omitido: valores fuera del rango 1-5.", nombre)
            continue
        validos.append({"nombre": nombre, "p": p, "i": i, "pr": pr, "ir": ir})
    return validos


def crear_figura_matriz(riesgos: list[dict[str, Any]], mostrar_residual: bool = True) -> Figure:
    """Crea la figura: dispersión Probabilidad vs. Impacto y barras de puntaje antes/después.

    No usa ``pyplot``, por lo que puede incrustarse en Tkinter con ``FigureCanvasTkAgg``.

    Args:
        riesgos: Documentos de ``riesgos_eticos``.
        mostrar_residual: Dibuja también el punto residual y una flecha desde el inherente.

    Raises:
        ErrorRiesgosEticos: Si no hay riesgos válidos que graficar.
    """
    datos = _validos(riesgos)
    if not datos:
        raise ErrorRiesgosEticos("No hay riesgos válidos para graficar.")

    fig = Figure(figsize=(10, 4.6), dpi=100)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.25, 1])
    ax = fig.add_subplot(gs[0])
    axb = fig.add_subplot(gs[1])

    # --- Dispersión ---
    for x in range(1, 6):
        for y in range(1, 6):
            ax.add_patch(Rectangle((x - 0.5, y - 0.5), 1, 1, facecolor=_color(x * y),
                                   alpha=0.13, linewidth=0))
    ocupadas: dict[tuple[float, float], int] = {}
    for n, r in enumerate(datos, start=1):
        r["etiqueta"] = f"R{n}"
        clave = (r["p"], r["i"])
        k = ocupadas.get(clave, 0)
        ocupadas[clave] = k + 1
        r["dx"] = 0.2 * k   # desplazamiento leve si coinciden en la misma celda

    for r in datos:
        x, y = r["p"] + r["dx"], r["i"] - r["dx"]
        ax.scatter(x, y, s=210, c=_color(r["p"] * r["i"]), edgecolors="black", linewidths=0.8, zorder=3)
        ax.annotate(r["etiqueta"], (x, y), ha="center", va="center", fontsize=7, color="white",
                    fontweight="bold", zorder=4)
        if mostrar_residual and (r["pr"], r["ir"]) != (r["p"], r["i"]):
            xr, yr = r["pr"] + r["dx"], r["ir"] - r["dx"]
            ax.annotate("", xy=(xr, yr), xytext=(x, y), zorder=2,
                        arrowprops=dict(arrowstyle="->", color="gray", lw=1, linestyle="--"))
            ax.scatter(xr, yr, s=150, marker="D", c=_color(r["pr"] * r["ir"]), edgecolors="black",
                       linewidths=0.8, zorder=3)
            ax.annotate(r["etiqueta"], (xr, yr), ha="center", va="center", fontsize=6, color="white",
                        fontweight="bold", zorder=4)

    ax.set_xlim(0.5, 5.5)
    ax.set_ylim(0.5, 5.5)
    ax.set_xticks(range(1, 6))
    ax.set_yticks(range(1, 6))
    ax.set_xlabel("Probabilidad")
    ax.set_ylabel("Impacto")
    ax.set_title("Matriz de riesgos (● inherente, ◆ residual)", fontsize=10)
    ax.grid(True, linestyle="--", alpha=0.4, zorder=1)
    leyenda = [
        Rectangle((0, 0), 1, 1, fc=COLOR_ALTO, label=f"Alto (≥ {config.get('umbral_riesgo_alto')})"),
        Rectangle((0, 0), 1, 1, fc=COLOR_MEDIO, label=f"Medio (≥ {config.get('umbral_riesgo_medio')})"),
        Rectangle((0, 0), 1, 1, fc=COLOR_BAJO, label="Bajo"),
    ]
    ax.legend(handles=leyenda, title="Severidad", loc="lower left", fontsize=7, title_fontsize=7)

    # --- Barras antes/después ---
    ys = list(range(len(datos)))
    antes = [r["p"] * r["i"] for r in datos]
    despues = [r["pr"] * r["ir"] for r in datos]
    alto = 0.38
    axb.barh([y - alto / 2 for y in ys], antes, height=alto, color="#c0504d", label="Antes (inherente)")
    axb.barh([y + alto / 2 for y in ys], despues, height=alto, color="#4f81bd", label="Después (residual)")
    axb.set_yticks(ys)
    axb.set_yticklabels([f"{r['etiqueta']} {r['nombre'][:24]}" for r in datos], fontsize=7)
    axb.invert_yaxis()
    axb.set_xlim(0, 25)
    axb.set_xlabel("Puntaje (probabilidad × impacto)")
    axb.set_title("Riesgo antes y después de la mitigación", fontsize=10)
    axb.axvline(config.get("umbral_riesgo_alto"), color="gray", linestyle=":", linewidth=1)
    axb.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    return fig
