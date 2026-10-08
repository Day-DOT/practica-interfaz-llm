"""Base de datos (MongoDB), clasificador de correos (LLM + palabras clave) y asistente RAG."""
import json
import os
import re
from typing import Literal

import ollama
from dotenv import load_dotenv
from pydantic import BaseModel
from pymongo import MongoClient

MODELO = "llama3.2"
SIN_INFO = "No tengo información en los registros."
PRIORIDAD = {"Baja": 0, "Media": 1, "Alta": 2}


def conectar():
    """Conecta a MongoDB con MONGO_URI y MONGO_DB del archivo .env y devuelve la base."""
    load_dotenv()
    if os.getenv("MONGO_URI", "").startswith("mongomock"):      # modo local en memoria, sin cluster
        import mongomock
        return mongomock.MongoClient()[os.getenv("MONGO_DB", "local")]
    cliente = MongoClient(os.getenv("MONGO_URI"), serverSelectionTimeoutMS=5000)
    cliente.admin.command("ping")                       # falla si no hay conexión
    return cliente[os.getenv("MONGO_DB")]


# ---------------------------------------------------------------- clasificador
class Incidente(BaseModel):
    categoria: Literal["Seguridad", "Documentación", "Logística", "Otro"]
    prioridad: Literal["Alta", "Media", "Baja"]
    entidades: list[str] = []
    resumen: str


PALABRAS = {
    "Seguridad": ["fuga", "derrame", "incendio", "accidente", "robo", "herido", "sello", "peligro"],
    "Documentación": ["certificado", "licencia", "permiso", "vencido", "documento", "poliza", "firma"],
    "Logística": ["retraso", "entrega", "ruta", "carga", "averia", "bodega", "demora"],
}
URGENTE = ["urgente", "fuga", "incendio", "accidente", "herido", "derrame", "emergencia"]


def clasificar_por_reglas(correo):
    texto = correo.lower().translate(str.maketrans("áéíóú", "aeiou"))
    cuenta = {c: sum(p in texto for p in ps) for c, ps in PALABRAS.items()}
    categoria = max(cuenta, key=cuenta.get) if max(cuenta.values()) > 0 else "Otro"
    if any(p in texto for p in URGENTE):
        prioridad = "Alta"
    else:
        prioridad = "Media" if categoria != "Otro" else "Baja"
    return Incidente(categoria=categoria, prioridad=prioridad, resumen=correo[:150])


def clasificar_con_llm(correo):
    """Pide JSON al LLM y lo valida con pydantic; reintenta una vez. Devuelve None si falla."""
    pedido = ('Clasifica este correo. Responde SOLO un JSON con las claves: "categoria" '
              '(Seguridad, Documentación, Logística u Otro), "prioridad" (Alta, Media o Baja), '
              '"entidades" (lista de placas o IDs) y "resumen" (texto breve).\n\nCorreo:\n' + correo)
    for _ in range(2):
        try:
            r = ollama.chat(model=MODELO, messages=[{"role": "user", "content": pedido}], format="json")
            return Incidente(**json.loads(r["message"]["content"]))
        except Exception:
            continue
    return None


def combinar(llm, reglas):
    """Une LLM y reglas. Devuelve (Incidente final, requiere_revision_humana)."""
    if llm is None:                                   # el LLM falló: se usan solo las reglas
        return reglas, False
    revision = (llm.categoria, llm.prioridad) != (reglas.categoria, reglas.prioridad)
    if PRIORIDAD[reglas.prioridad] > PRIORIDAD[llm.prioridad]:      # prevalece la prioridad más alta
        llm.prioridad = reglas.prioridad
    return llm, revision


def clasificar(correo):
    return combinar(clasificar_con_llm(correo), clasificar_por_reglas(correo))


# ---------------------------------------------------------------------- RAG
def preguntar(db, pregunta):
    """Busca registros en accesos e incidentes y responde SOLO con ellos."""
    limpia = re.sub(r"[¿?¡!.,;:()]", " ", pregunta.lower())
    palabras = [p[:5] for p in limpia.split() if len(p) > 3]       # raíz: "denegados" encuentra "denegado"
    encontrados, recientes = [], []
    for coleccion in ("accesos", "incidentes"):
        for doc in db[coleccion].find().sort("_id", -1).limit(200):
            doc.pop("_id")
            motivo = " ".join(doc.pop("explicacion", []))[:600]
            if coleccion == "accesos" and "A" in doc:
                si = lambda v: "sí" if v else "no"
                doc_a, p, s, q = doc["A"], doc.get("P"), doc.get("S"), doc.get("Q")
                doc = {"placa": doc.get("placa"), "fecha": doc.get("fecha"),
                       "resultado": "DENEGADO" if not doc["A"] else "AUTORIZADO",
                       "inspección requerida": si(doc.get("E")),
                       "autorización previa": si(doc.get("P")), "peso excedido": si(doc.get("Q")),
                       "materiales peligrosos": si(doc.get("R")), "certificación vigente": si(doc.get("S"))}
                if not doc_a:
                    faltas = [t for ok, t in ((p, "no tenía autorización previa"), (s, "no tenía certificación vigente"))
                              if not ok] + (["el peso estaba excedido"] if q else [])
                    doc["motivo de la denegación"] = " y ".join(faltas)
            texto = json.dumps(doc, default=str, ensure_ascii=False) + " Explicación: " + motivo
            registro = f"[{coleccion}] {texto[:700]}"
            if len(recientes) < 8:
                recientes.append((0, registro))
            puntos = sum(p in (coleccion + " " + texto).lower() for p in palabras)   # "incidentes" encuentra la colección
            if puntos:
                encontrados.append((puntos, registro))
    if not encontrados:
        encontrados = recientes            # sin coincidencias: el LLM decide con los registros más recientes
    if not encontrados:
        return SIN_INFO
    placas = sorted({d["placa"] for d in db.accesos.find({}, {"placa": 1}) if d.get("placa")})
    lista = lambda filtro: ", ".join(sorted(set(db.accesos.distinct("placa", filtro)))) or "ninguna"
    resumen = (f"[resumen] Total de accesos: {db.accesos.count_documents({})}; "
               f"autorizados: {db.accesos.count_documents({'A': True})}; "
               f"denegados: {db.accesos.count_documents({'A': False})}; "
               f"con inspección: {db.accesos.count_documents({'E': True})}; "
               f"placas con al menos un acceso denegado: {lista({'A': False})}; "
               f"placas con al menos un acceso autorizado: {lista({'A': True})}; "
               f"placas enviadas a inspección: {lista({'E': True})}; "
               f"total de camiones distintos: {len(placas)} (todas las placas: {', '.join(placas)}); "
               f"incidentes: {db.incidentes.count_documents({})}")
    contexto = resumen + "\n" + "\n".join(t for _, t in sorted(encontrados, reverse=True)[:8])
    r = ollama.chat(model=MODELO, messages=[
        {"role": "system", "content": "Responde en español SOLO con el contexto dado y cita el registro. "
                                      "La línea [resumen] contiene totales ya calculados: úsala para preguntas de conteo. "
                                      f'Si no está en el contexto responde exactamente: "{SIN_INFO}"'},
        {"role": "user", "content": f"Contexto:\n{contexto}\n\nPregunta: {pregunta}"}])
    respuesta = r["message"]["content"].split("Tú:")[0].strip()    # corta si el modelo inventa más turnos
    if not respuesta or respuesta.lower().startswith("no tengo informaci"):
        # el modelo se rindió: se muestran los datos reales de la base en vez de una negativa vacía
        return ("No pude responder esa pregunta en concreto, pero esto es lo que hay registrado:\n"
                + resumen.replace("[resumen] ", "").replace("; ", "\n- ")
                + "\nPrueba preguntando por una placa (ej. TRK-103), por 'incidentes' o por 'denegados'.")
    return respuesta


# ------------------------------------------------------------------- riesgos
RIESGOS = [  # nombre, probabilidad, impacto, prob. residual, impacto residual, mitigación
    ("Alucinaciones del LLM", 4, 4, 2, 4, "Responder solo con datos de MongoDB y citar la fuente"),
    ("Sesgo por ortografía informal", 4, 3, 3, 2, "Fusionar con reglas y revisión humana"),
    ("Privacidad del conductor", 3, 5, 2, 3, "LLM local y minimizar los datos"),
    ("Dependencia de la automatización", 4, 4, 3, 3, "Explicar cada decisión y marcar casos dudosos"),
]


def riesgos(db):
    """Devuelve los riesgos de MongoDB; si la colección está vacía inserta los 4 iniciales."""
    if db.riesgos_eticos.count_documents({}) == 0:
        claves = ("nombre", "probabilidad", "impacto", "probabilidad_residual", "impacto_residual", "mitigacion")
        db.riesgos_eticos.insert_many([dict(zip(claves, r)) for r in RIESGOS])
    return list(db.riesgos_eticos.find())
