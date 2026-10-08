"""
datos_demo.py
=============
Carga datos de demostración en MongoDB (camiones, accesos e incidentes).

Todos los documentos sembrados llevan ``"demo": True``, de modo que se pueden borrar o
regenerar sin tocar los registros reales. Los accesos se calculan con el motor de reglas
real (misma explicación paso a paso que en la GUI) y los incidentes se clasifican con las
reglas (sin LLM, para que la carga sea instantánea). Los riesgos éticos los siembra
``riesgos_eticos.obtener_riesgos`` y las evaluaciones del LLM se generan al usar la app.

Uso::

    python datos_demo.py              # siembra si no hay datos demo
    python datos_demo.py --reiniciar  # borra los datos demo y los vuelve a crear
"""

from __future__ import annotations

import logging
import random
from datetime import date, datetime, time, timedelta
from typing import Any

from pymongo.database import Database
from pymongo.errors import PyMongoError

import clasificador_hibrido as ch
import repositorio
from evaluacion_clasificador import cargar_dataset
from motor_reglas import evaluar_acceso
from riesgos_eticos import obtener_riesgos

logger = logging.getLogger(__name__)

#: (placa, camion_id, empresa, autorizado, conductor, días hasta el vencimiento de la certificación)
CAMIONES_DEMO: list[tuple[str, str, str, bool, str, int]] = [
    ("ABC-123", "CAM-101", "TransNorte SA", True, "Juan Pérez", 200),
    ("XYZ-789", "CAM-102", "LogiSur", True, "María López", 45),
    ("DEF-456", "CAM-103", "Carga Rápida", True, "Carlos Ruiz", -20),
    ("GHI-321", "CAM-104", "TransNorte SA", False, "Luis Gómez", 90),
    ("JKL-654", "CAM-105", "QuímicaMex", True, "Ana Torres", 10),
    ("MNO-852", "CAM-106", "QuímicaMex", True, "Pedro Díaz", -5),
    ("PQR-147", "CAM-107", "FrioExpress", True, "Sofía Ramos", 300),
    ("STU-963", "CAM-108", "Carga Rápida", True, "Jorge Mena", 120),
]
OPERADORES: tuple[str, ...] = ("operador1", "operador2")


def _sembrar_camiones(db: Database, hoy: date) -> list[dict[str, Any]]:
    """Inserta los camiones demo que no existan. Retorna los documentos demo (con vigencia)."""
    camiones = []
    for placa, camion_id, empresa, autorizado, conductor, dias in CAMIONES_DEMO:
        vigencia = datetime.combine(hoy + timedelta(days=dias), time.min)
        doc = {
            "placa": placa, "camion_id": camion_id, "empresa": empresa, "autorizacion": autorizado,
            "certificacion_conductor": {"conductor": conductor, "vigencia": vigencia},
            "fecha_registro": datetime.now(), "demo": True,
        }
        db["camiones"].update_one({"placa": placa}, {"$setOnInsert": doc}, upsert=True)
        camiones.append(doc)
    return camiones


def _sembrar_accesos(db: Database, camiones: list[dict[str, Any]], hoy: date, azar: random.Random) -> int:
    """Inserta ~40 accesos de las últimas 4 semanas, calculados con el motor de reglas real."""
    escenarios: list[tuple[dict[str, Any], datetime, dict[str, bool]]] = []

    # Caso garantizado para la demo del asistente: CAM-102 enviado a inspección por riesgo de ruta.
    cam102 = next(c for c in camiones if c["camion_id"] == "CAM-102")
    escenarios.append((cam102, datetime.combine(hoy - timedelta(days=1), time(9, 30)),
                       {"P": True, "Q": False, "R": True, "S": True}))

    for _ in range(39):
        camion = azar.choice(camiones)
        dia = hoy - timedelta(days=azar.randint(0, 27))
        momento = datetime.combine(dia, time(azar.randint(5, 21), azar.choice((0, 15, 30, 45))))
        premisas = {
            "P": camion["autorizacion"] and azar.random() > 0.08,
            "Q": azar.random() < 0.15,
            "R": camion["empresa"] == "QuímicaMex" and azar.random() < 0.8,
            "S": azar.random() > 0.12,
        }
        escenarios.append((camion, momento, premisas))

    for camion, momento, premisas in escenarios:
        vigencia = camion["certificacion_conductor"]["vigencia"].date()
        resultado = evaluar_acceso(
            **premisas, vigencia_certificacion=vigencia,
            hora_ingreso=momento.time(), fecha_evaluacion=momento.date(),
        )
        repositorio.registrar_acceso(
            db, placa=camion["placa"], camion_id=camion["camion_id"], operador=azar.choice(OPERADORES),
            premisas=premisas, resultado=resultado, vigencia=vigencia,
            hora_ingreso=momento.strftime("%H:%M"), fecha=momento, extra={"demo": True},
        )
    return len(escenarios)


def _sembrar_incidentes(db: Database, hoy: date, azar: random.Random) -> int:
    """Clasifica con reglas 18 correos del conjunto etiquetado y los reparte en 5 semanas."""
    correos = azar.sample(cargar_dataset(), 18)
    for n, item in enumerate(correos):
        clasif = ch.clasificar_por_reglas(item["texto"])
        momento = datetime.combine(hoy - timedelta(days=azar.randint(0, 34)), time(azar.randint(7, 19), 0))
        estado = azar.choices(repositorio.ESTADOS_INCIDENTE, weights=(4, 3, 3))[0]
        id_inc = repositorio.crear_incidente(
            db, correo=item["texto"],
            clasificacion={"categoria": clasif.categoria, "prioridad": clasif.prioridad,
                           "origen": clasif.origen,
                           "requiere_revision_humana": clasif.requiere_revision_humana},
            datos_extraidos={"entidades": clasif.entidades, "resumen": clasif.resumen},
            estado="nuevo", fecha=momento, extra={"demo": True},
        )
        if estado != "nuevo":
            repositorio.cambiar_estado_incidente(db, id_inc, estado)
    return len(correos)


def sembrar(db: Database, reiniciar: bool = False) -> dict[str, int]:
    """Siembra los datos de demostración.

    Args:
        db: Base de datos conectada.
        reiniciar: Si es ``True`` borra antes los documentos ``demo`` (y solo esos).

    Returns:
        Cantidad insertada por colección (vacío si ya había datos demo y no se reinició).

    Raises:
        repositorio.ErrorRepositorio: Si falla MongoDB.
    """
    try:
        if reiniciar:
            for coleccion in ("camiones", "accesos", "incidentes"):
                db[coleccion].delete_many({"demo": True})
        elif db["camiones"].count_documents({"demo": True}) > 0:
            logger.info("Ya existen datos de demostración; no se vuelve a sembrar.")
            return {}

        azar = random.Random(42)  # reproducible
        hoy = date.today()
        camiones = _sembrar_camiones(db, hoy)
        n_accesos = _sembrar_accesos(db, camiones, hoy, azar)
        n_incidentes = _sembrar_incidentes(db, hoy, azar)
        n_riesgos = len(obtener_riesgos(db))
        return {"camiones": len(camiones), "accesos": n_accesos, "incidentes": n_incidentes,
                "riesgos_eticos": n_riesgos}
    except PyMongoError as exc:
        raise repositorio.ErrorRepositorio(f"No se pudieron sembrar los datos de demostración: {exc}") from exc


if __name__ == "__main__":
    import sys

    from conexion import ErrorConexionBD, cerrar_conexion, obtener_db

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        cantidades = sembrar(obtener_db(), reiniciar="--reiniciar" in sys.argv)
        print("Datos de demostración:", cantidades or "ya existían (usa --reiniciar para regenerarlos)")
    except (ErrorConexionBD, repositorio.ErrorRepositorio) as error:
        print(f"[ERROR] {error}")
        raise SystemExit(1)
    finally:
        cerrar_conexion()
