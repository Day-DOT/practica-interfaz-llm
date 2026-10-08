"""
evaluacion_clasificador.py
==========================
Experimento de clasificación: compara **reglas**, **LLM** e **híbrido** sobre un conjunto
de correos etiquetados a mano (``datos/correos_etiquetados.json``, 35 correos).

Métricas por método:
    * Exactitud de categoría, de prioridad y conjunta (ambas correctas).
    * Matriz de confusión de la categoría.
    * Latencia media / mediana / p95 (ms).
    * Para el LLM: número de respuestas inválidas que obligaron a usar el respaldo.

El híbrido se calcula con la misma salida del LLM de cada correo (se llama al LLM una
sola vez por correo), por lo que su latencia es la del LLM más la de las reglas.

Uso::

    python evaluacion_clasificador.py            # reglas + LLM + híbrido (requiere Ollama)
    python evaluacion_clasificador.py --sin-llm  # solo reglas

Los resultados se guardan en ``resultados/`` (JSON, CSV y PNG).
"""

from __future__ import annotations

import csv
import json
import logging
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from matplotlib.figure import Figure
from pymongo.database import Database

import clasificador_hibrido as ch
import config

logger = logging.getLogger(__name__)

RUTA_DATASET: Path = Path(__file__).with_name("datos") / "correos_etiquetados.json"
CARPETA_RESULTADOS: Path = Path(__file__).with_name("resultados")
METODOS: tuple[str, ...] = ("reglas", "llm", "hibrido")
ETIQUETAS_METODO: dict[str, str] = {"reglas": "Reglas", "llm": "LLM", "hibrido": "Híbrido"}


def cargar_dataset(ruta: Optional[Path] = None) -> list[dict[str, Any]]:
    """Carga el conjunto de correos etiquetados.

    Raises:
        FileNotFoundError / ValueError: Si el archivo no existe o está mal formado.
    """
    datos = json.loads((ruta or RUTA_DATASET).read_text(encoding="utf-8"))
    if not isinstance(datos, list) or not datos:
        raise ValueError("El conjunto de correos etiquetados está vacío o mal formado.")
    return datos


def matriz_confusion(reales: list[str], predichos: list[Optional[str]], etiquetas: tuple[str, ...]) -> list[list[int]]:
    """Matriz ``[real][predicho]``; una predicción ``None`` (fallo) no se cuenta."""
    indice = {e: i for i, e in enumerate(etiquetas)}
    matriz = [[0] * len(etiquetas) for _ in etiquetas]
    for real, pred in zip(reales, predichos):
        if pred in indice:
            matriz[indice[real]][indice[pred]] += 1
    return matriz


def _exactitud(reales: list[str], predichos: list[Optional[str]]) -> float:
    return sum(1 for r, p in zip(reales, predichos) if r == p) / len(reales) if reales else 0.0


def _latencias(valores: list[float]) -> dict[str, float]:
    if not valores:
        return {"media": 0.0, "mediana": 0.0, "p95": 0.0}
    ordenado = sorted(valores)
    p95 = ordenado[min(len(ordenado) - 1, int(round(0.95 * (len(ordenado) - 1))))]
    return {"media": round(statistics.fmean(valores), 1), "mediana": round(statistics.median(valores), 1),
            "p95": round(p95, 1)}


def ejecutar_experimento(
    usar_llm: bool = True,
    progreso: Optional[Callable[[int, int, str], None]] = None,
    db: Optional[Database] = None,
    guardar: bool = True,
) -> dict[str, Any]:
    """Ejecuta el experimento completo.

    Args:
        usar_llm: Si es ``False`` solo se evalúan las reglas.
        progreso: Callback ``(hechos, total, mensaje)`` (se invoca desde el hilo que ejecuta).
        db: Si se indica, cada llamada al LLM se registra en ``evaluaciones_llm``.
        guardar: Escribe JSON/CSV/PNG en ``resultados/``.

    Returns:
        Diccionario con ``metricas`` por método, ``predicciones`` por correo y metadatos.
    """
    dataset = cargar_dataset()
    total = len(dataset)
    categorias = ch.CATEGORIAS_VALIDAS
    filas: list[dict[str, Any]] = []
    lat: dict[str, list[float]] = {m: [] for m in METODOS}
    fallos_llm = 0
    inicio_total = time.perf_counter()

    for n, item in enumerate(dataset, start=1):
        if progreso:
            progreso(n - 1, total, f"Correo {n}/{total}")
        res = ch.clasificar_correo_detallado(item["texto"], usar_llm=usar_llm)
        if db is not None and res.intentos:
            try:
                import repositorio
                repositorio.registrar_clasificacion(db, res)
            except Exception as exc:  # el registro nunca debe romper el experimento
                logger.warning("No se pudo registrar la evaluación: %s", exc)

        lat_llm = sum(i.latencia_ms for i in res.intentos)
        if usar_llm and res.llm is None:
            fallos_llm += 1
        lat["reglas"].append(res.latencia_reglas_ms)
        if usar_llm:
            lat["llm"].append(lat_llm)
            lat["hibrido"].append(res.latencia_total_ms)

        filas.append({
            "id": item["id"], "formal": item.get("formal", True), "texto": item["texto"],
            "real_categoria": item["categoria"], "real_prioridad": item["prioridad"],
            "reglas_categoria": res.reglas.categoria, "reglas_prioridad": res.reglas.prioridad,
            "llm_categoria": res.llm.categoria if res.llm else None,
            "llm_prioridad": res.llm.prioridad if res.llm else None,
            "hibrido_categoria": res.final.categoria, "hibrido_prioridad": res.final.prioridad,
            "hibrido_revision_humana": res.final.requiere_revision_humana,
        })

    metodos = [m for m in METODOS if m == "reglas" or usar_llm]
    reales_c = [f["real_categoria"] for f in filas]
    reales_p = [f["real_prioridad"] for f in filas]
    metricas: dict[str, Any] = {}
    for m in metodos:
        pc = [f[f"{m}_categoria"] for f in filas]
        pp = [f[f"{m}_prioridad"] for f in filas]
        conjunta = sum(1 for f in filas if f[f"{m}_categoria"] == f["real_categoria"]
                       and f[f"{m}_prioridad"] == f["real_prioridad"]) / total
        # Exactitud en correos informales (sesgo ortográfico)
        informales = [f for f in filas if not f["formal"]]
        formales = [f for f in filas if f["formal"]]
        metricas[m] = {
            "exactitud_categoria": round(_exactitud(reales_c, pc), 4),
            "exactitud_prioridad": round(_exactitud(reales_p, pp), 4),
            "exactitud_conjunta": round(conjunta, 4),
            "exactitud_categoria_formales": round(_exactitud(
                [f["real_categoria"] for f in formales], [f[f"{m}_categoria"] for f in formales]), 4),
            "exactitud_categoria_informales": round(_exactitud(
                [f["real_categoria"] for f in informales], [f[f"{m}_categoria"] for f in informales]), 4),
            "matriz_confusion_categoria": matriz_confusion(reales_c, pc, categorias),
            "latencia_ms": _latencias(lat[m]),
        }
    metricas["_resumen"] = {
        "correos": total, "usar_llm": usar_llm, "fallos_llm": fallos_llm,
        "revision_humana_hibrido": sum(1 for f in filas if f["hibrido_revision_humana"]),
        "modelo": config.get("modelo_ollama") if usar_llm else None,
        "etiquetas_categoria": list(categorias),
        "duracion_s": round(time.perf_counter() - inicio_total, 1),
        "fecha": datetime.now().isoformat(timespec="seconds"),
    }
    resultado = {"metricas": metricas, "predicciones": filas}

    if progreso:
        progreso(total, total, "Experimento completado")
    if guardar:
        resultado["archivos"] = guardar_resultados(resultado)
    return resultado


# --------------------------------------------------------------------------- #
# Presentación
# --------------------------------------------------------------------------- #
def resumen_texto(resultado: dict[str, Any]) -> str:
    """Resumen legible (tabla de exactitud y latencia)."""
    met = resultado["metricas"]
    res = met["_resumen"]
    lineas = [
        f"Experimento de clasificación - {res['correos']} correos etiquetados "
        f"(modelo: {res['modelo'] or 'sin LLM'}, {res['duracion_s']} s)",
        "",
        f"{'Método':<10}{'Cat.':>8}{'Prior.':>9}{'Ambas':>8}{'Formales':>10}{'Informales':>12}"
        f"{'Lat. media':>13}{'Lat. p95':>11}",
    ]
    for m in METODOS:
        if m not in met:
            continue
        d = met[m]
        lineas.append(
            f"{ETIQUETAS_METODO[m]:<10}{d['exactitud_categoria']:>8.1%}{d['exactitud_prioridad']:>9.1%}"
            f"{d['exactitud_conjunta']:>8.1%}{d['exactitud_categoria_formales']:>10.1%}"
            f"{d['exactitud_categoria_informales']:>12.1%}"
            f"{d['latencia_ms']['media']:>10.0f} ms{d['latencia_ms']['p95']:>8.0f} ms"
        )
    lineas += ["", "(Cat./Prior./Ambas = exactitud sobre todos los correos; Formales/Informales = "
                   "exactitud de categoría según la ortografía del correo.)"]
    if res["usar_llm"]:
        lineas.append(f"Respuestas del LLM inválidas tras reintentos (se usó respaldo): {res['fallos_llm']}")
        lineas.append(f"Correos que el híbrido marcó para revisión humana: {res['revision_humana_hibrido']}")
    return "\n".join(lineas)


def crear_figura_confusion(resultado: dict[str, Any]) -> Figure:
    """Figura con la matriz de confusión de la categoría de cada método (sin pyplot)."""
    met = resultado["metricas"]
    metodos = [m for m in METODOS if m in met]
    etiquetas = met["_resumen"]["etiquetas_categoria"]
    fig = Figure(figsize=(4.2 * len(metodos), 4.2), dpi=100)
    for k, m in enumerate(metodos, start=1):
        ax = fig.add_subplot(1, len(metodos), k)
        matriz = met[m]["matriz_confusion_categoria"]
        ax.imshow(matriz, cmap="Blues")
        ax.set_xticks(range(len(etiquetas)))
        ax.set_yticks(range(len(etiquetas)))
        ax.set_xticklabels(etiquetas, rotation=35, ha="right", fontsize=8)
        ax.set_yticklabels(etiquetas, fontsize=8)
        ax.set_xlabel("Predicho")
        ax.set_ylabel("Real")
        ax.set_title(f"{ETIQUETAS_METODO[m]} ({met[m]['exactitud_categoria']:.0%})", fontsize=10)
        maximo = max(max(f) for f in matriz) or 1
        for i, fila in enumerate(matriz):
            for j, v in enumerate(fila):
                ax.text(j, i, v, ha="center", va="center", fontsize=9,
                        color="white" if v > maximo / 2 else "black")
    fig.tight_layout()
    return fig


def guardar_resultados(resultado: dict[str, Any]) -> dict[str, str]:
    """Escribe ``resultados/experimento_clasificacion.{json,csv,png}`` y devuelve las rutas."""
    CARPETA_RESULTADOS.mkdir(exist_ok=True)
    ruta_json = CARPETA_RESULTADOS / "experimento_clasificacion.json"
    ruta_csv = CARPETA_RESULTADOS / "experimento_clasificacion.csv"
    ruta_png = CARPETA_RESULTADOS / "matrices_confusion.png"
    ruta_txt = CARPETA_RESULTADOS / "experimento_resumen.txt"

    ruta_json.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    filas = resultado["predicciones"]
    with open(ruta_csv, "w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)
    crear_figura_confusion(resultado).savefig(ruta_png, bbox_inches="tight")
    ruta_txt.write_text(resumen_texto(resultado), encoding="utf-8")
    return {"json": str(ruta_json), "csv": str(ruta_csv), "png": str(ruta_png), "txt": str(ruta_txt)}


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    sin_llm = "--sin-llm" in sys.argv
    salida = ejecutar_experimento(
        usar_llm=not sin_llm,
        progreso=lambda h, t, m: print(f"\r{m}   ", end="", flush=True),
    )
    print("\n")
    print(resumen_texto(salida))
    print("\nArchivos:", *salida["archivos"].values(), sep="\n  ")
