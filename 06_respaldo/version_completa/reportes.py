"""
reportes.py
===========
Exportación de datos a CSV, JSON y PDF.

``obtener_datos(db, tema, desde, hasta)`` lee la información; ``exportar(...)`` la escribe
en el formato pedido. El PDF se genera con matplotlib (sin dependencias extra).

Temas disponibles: ``accesos``, ``incidentes``, ``camiones``, ``riesgos_eticos`` y
``evaluaciones_llm``.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import textwrap
from datetime import date, datetime
from typing import Any, Optional

from bson import ObjectId
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from pymongo.database import Database
from pymongo.errors import PyMongoError

import repositorio

logger = logging.getLogger(__name__)

TEMAS: dict[str, str] = {
    "accesos": "Bitácora de accesos",
    "incidentes": "Incidentes",
    "camiones": "Camiones",
    "riesgos_eticos": "Riesgos éticos",
    "evaluaciones_llm": "Evaluaciones del LLM",
}
FORMATOS: tuple[str, ...] = ("CSV", "JSON", "PDF")

#: Columnas (ruta con puntos) que se muestran en el PDF para cada tema.
COLUMNAS_PDF: dict[str, list[str]] = {
    "accesos": ["fecha", "placa", "operador", "P", "Q", "R", "S", "A", "E", "decision"],
    "incidentes": ["fecha", "clasificacion.categoria", "clasificacion.prioridad", "estado",
                   "datos_extraidos.resumen"],
    "camiones": ["placa", "camion_id", "empresa", "autorizacion",
                 "certificacion_conductor.conductor", "certificacion_conductor.vigencia"],
    "riesgos_eticos": ["modulo", "nombre", "categoria", "probabilidad", "impacto",
                       "probabilidad_residual", "impacto_residual"],
    "evaluaciones_llm": ["fecha", "tipo", "modelo", "latencia_ms", "coincide_con_reglas", "valido"],
}


class ErrorReporte(Exception):
    """Fallo al obtener datos o al escribir el archivo de reporte."""


# --------------------------------------------------------------------------- #
# Datos
# --------------------------------------------------------------------------- #
def _serializable(valor: Any) -> Any:
    """Convierte ObjectId/datetime a texto, recursivamente."""
    if isinstance(valor, dict):
        return {k: _serializable(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_serializable(v) for v in valor]
    if isinstance(valor, ObjectId):
        return str(valor)
    if isinstance(valor, datetime):
        return valor.isoformat(timespec="seconds")
    if isinstance(valor, date):
        return valor.isoformat()
    return valor


def obtener_datos(
    db: Database, tema: str, desde: Optional[date] = None, hasta: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Lee los registros de ``tema`` (serializables a JSON).

    Raises:
        ErrorReporte: Si el tema no existe o falla MongoDB.
    """
    if tema not in TEMAS:
        raise ErrorReporte(f"Tema de reporte desconocido: {tema}")
    try:
        if tema == "accesos":
            docs = repositorio.listar_accesos(db, desde, hasta, limite=5000)
        elif tema == "incidentes":
            docs = repositorio.listar_incidentes(db, desde=desde, hasta=hasta, limite=5000)
        elif tema == "evaluaciones_llm":
            docs = repositorio.listar_evaluaciones(db, desde, hasta, limite=5000)
        elif tema == "camiones":
            docs = repositorio.listar_camiones(db)
        else:
            docs = list(db["riesgos_eticos"].find().sort("_id", 1))
    except (repositorio.ErrorRepositorio, PyMongoError) as exc:
        raise ErrorReporte(str(exc)) from exc
    return [_serializable(d) for d in docs]


def _aplanar(valor: Any, prefijo: str = "") -> dict[str, Any]:
    """Aplana diccionarios anidados con claves ``a.b``; las listas se unen en un texto."""
    plano: dict[str, Any] = {}
    if isinstance(valor, dict):
        for k, v in valor.items():
            plano.update(_aplanar(v, f"{prefijo}.{k}" if prefijo else k))
    elif isinstance(valor, list):
        if all(not isinstance(x, (dict, list)) for x in valor):
            plano[prefijo] = " | ".join(str(x) for x in valor)
        else:
            plano[prefijo] = json.dumps(valor, ensure_ascii=False)
    else:
        plano[prefijo] = valor
    return plano


# --------------------------------------------------------------------------- #
# Escritura
# --------------------------------------------------------------------------- #
def exportar_json(registros: list[dict[str, Any]], ruta: str) -> None:
    """Escribe los registros como JSON (UTF-8, con sangría)."""
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(registros, f, ensure_ascii=False, indent=2)


def exportar_csv(registros: list[dict[str, Any]], ruta: str) -> None:
    """Escribe los registros aplanados como CSV (UTF-8 con BOM, abre bien en Excel)."""
    filas = [_aplanar(r) for r in registros]
    columnas: list[str] = []
    for fila in filas:
        for clave in fila:
            if clave not in columnas:
                columnas.append(clave)
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(filas)


def exportar_pdf(registros: list[dict[str, Any]], ruta: str, tema: str, filas_por_pagina: int = 22) -> None:
    """Escribe una tabla resumen en PDF (A4 horizontal, varias páginas)."""
    columnas = COLUMNAS_PDF.get(tema) or sorted(_aplanar(registros[0]))[:8] if registros else []
    titulo = TEMAS.get(tema, tema)
    generado = datetime.now().strftime("%Y-%m-%d %H:%M")
    filas = [_aplanar(r) for r in registros]

    def celda(fila: dict[str, Any], col: str) -> str:
        valor = fila.get(col, "")
        if isinstance(valor, bool):
            valor = "Sí" if valor else "No"
        texto = "" if valor is None else str(valor).replace("T", " ")
        return textwrap.shorten(texto, width=34, placeholder="…")

    with PdfPages(ruta) as pdf:
        paginas = max(1, -(-len(filas) // filas_por_pagina))
        for n in range(paginas):
            fig = Figure(figsize=(11.69, 8.27))
            ax = fig.add_axes([0.03, 0.05, 0.94, 0.80])
            ax.axis("off")
            fig.text(0.03, 0.94, f"Reporte: {titulo}", fontsize=16, fontweight="bold")
            fig.text(0.03, 0.905, f"Generado: {generado}  ·  {len(filas)} registros  ·  "
                                  f"Página {n + 1}/{paginas}", fontsize=9, color="gray")
            bloque = filas[n * filas_por_pagina:(n + 1) * filas_por_pagina]
            if not columnas or not bloque:
                ax.text(0.5, 0.5, "Sin registros para mostrar.", ha="center", fontsize=12)
            else:
                tabla = ax.table(
                    cellText=[[celda(f, c) for c in columnas] for f in bloque],
                    colLabels=[c.split(".")[-1] for c in columnas],
                    loc="upper center", cellLoc="left",
                )
                tabla.auto_set_font_size(False)
                tabla.set_fontsize(7)
                tabla.auto_set_column_width(list(range(len(columnas))))
                for (fila, _), cel in tabla.get_celld().items():
                    cel.set_height(0.04)
                    if fila == 0:
                        cel.set_facecolor("#1f4e8c")
                        cel.get_text().set_color("white")
                        cel.get_text().set_fontweight("bold")
            pdf.savefig(fig)


def exportar(registros: list[dict[str, Any]], ruta: str, formato: str, tema: str = "") -> str:
    """Exporta ``registros`` a ``ruta`` en el ``formato`` indicado (CSV, JSON o PDF).

    Returns:
        Ruta absoluta del archivo creado.

    Raises:
        ErrorReporte: Si el formato es desconocido o no se puede escribir el archivo.
    """
    formato = formato.upper()
    if formato not in FORMATOS:
        raise ErrorReporte(f"Formato desconocido: {formato}")
    try:
        if formato == "JSON":
            exportar_json(registros, ruta)
        elif formato == "CSV":
            exportar_csv(registros, ruta)
        else:
            exportar_pdf(registros, ruta, tema)
    except OSError as exc:
        raise ErrorReporte(f"No se pudo escribir '{ruta}': {exc}") from exc
    return os.path.abspath(ruta)
