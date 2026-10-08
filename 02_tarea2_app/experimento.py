"""Experimento: compara reglas, LLM e híbrido con 35 correos etiquetados a mano.
Ejecutar: python experimento.py          (con LLM, tarda varios minutos)
          python experimento.py --sin-llm (solo reglas)
Resultados: carpeta ../03_datos/resultados"""
import json
import sys
import time
from pathlib import Path

import ia

DATOS = Path(__file__).resolve().parent.parent / "03_datos"
CATEGORIAS = ["Seguridad", "Documentación", "Logística", "Otro"]

correos = json.loads((DATOS / "correos_etiquetados.json").read_text(encoding="utf-8"))
con_llm = "--sin-llm" not in sys.argv
metodos = ["Reglas", "LLM", "Híbrido"] if con_llm else ["Reglas"]
pred = {m: [] for m in metodos}            # (categoria, prioridad) por correo
tiempos = {m: [] for m in metodos}         # latencia en segundos

for n, c in enumerate(correos, start=1):
    print(f"Correo {n}/{len(correos)}", flush=True)
    t0 = time.time()
    reglas = ia.clasificar_por_reglas(c["texto"])
    t_reglas = time.time() - t0
    pred["Reglas"].append((reglas.categoria, reglas.prioridad))
    tiempos["Reglas"].append(t_reglas)
    if con_llm:
        t0 = time.time()
        llm = ia.clasificar_con_llm(c["texto"])
        t_llm = time.time() - t0
        pred["LLM"].append((llm.categoria, llm.prioridad) if llm else (None, None))   # None = respuesta inválida
        final, _ = ia.combinar(llm, reglas)             # (combinar puede subir la prioridad del LLM)
        pred["Híbrido"].append((final.categoria, final.prioridad))
        tiempos["LLM"].append(t_llm)
        tiempos["Híbrido"].append(t_llm + t_reglas)

resultados = {}
for m in metodos:
    n = len(correos)
    ok_cat = sum(p[0] == c["categoria"] for p, c in zip(pred[m], correos))
    ok_pri = sum(p[1] == c["prioridad"] for p, c in zip(pred[m], correos))
    matriz = [[sum(c["categoria"] == real and p[0] == guess for p, c in zip(pred[m], correos))
               for guess in CATEGORIAS] for real in CATEGORIAS]
    resultados[m] = {"exactitud_categoria": round(ok_cat / n, 3), "exactitud_prioridad": round(ok_pri / n, 3),
                     "latencia_media_s": round(sum(tiempos[m]) / n, 2), "matriz_confusion": matriz}
    print(f"{m:8} categoría {ok_cat / n:.1%} | prioridad {ok_pri / n:.1%} | latencia media {sum(tiempos[m]) / n:.2f} s")

carpeta = DATOS / "resultados"
carpeta.mkdir(exist_ok=True)
(carpeta / "resultados.json").write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")

from matplotlib.figure import Figure          # gráfica con las matrices de confusión
fig = Figure(figsize=(4.5 * len(metodos), 4.2))
for i, m in enumerate(metodos, start=1):
    ax = fig.add_subplot(1, len(metodos), i)
    matriz = resultados[m]["matriz_confusion"]
    ax.imshow(matriz, cmap="RdPu")
    ax.set_xticks(range(4), CATEGORIAS, rotation=30, ha="right", fontsize=8)
    ax.set_yticks(range(4), CATEGORIAS, fontsize=8)
    ax.set(xlabel="Predicho", ylabel="Real", title=f"{m} ({resultados[m]['exactitud_categoria']:.0%})")
    for a in range(4):
        for b in range(4):
            ax.text(b, a, matriz[a][b], ha="center", va="center")
fig.tight_layout()
fig.savefig(carpeta / "matrices_confusion.png", dpi=130)
print("Guardado en", carpeta)
