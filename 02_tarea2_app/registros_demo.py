"""Agrega accesos e incidentes de ejemplo a MongoDB. Ejecutar: python registros_demo.py"""
from datetime import date, datetime, timedelta

import ia
import reglas

# placa, P, Q, R, S, vence, hora
CAMIONES = [
    ("TRK-101", True, False, False, True, date(2027, 8, 10), 8),
    ("TRK-102", False, False, False, True, date(2027, 5, 2), 11),     # sin autorización
    ("TRK-103", True, True, True, True, date(2027, 2, 14), 15),       # peso excedido + peligrosos
    ("TRK-104", True, False, True, True, date(2027, 9, 1), 23),       # peligrosos fuera de horario
    ("TRK-105", True, False, False, False, date(2025, 3, 5), 13),     # certificación vencida
    ("TRK-106", True, False, False, True, date(2027, 12, 30), 17),
]

INCIDENTES = [
    ("Fuga de combustible en el camión TRK-103 en la bodega 2, urgente.", "Seguridad", "Alta", ["TRK-103"]),
    ("El camión TRK-105 tiene la licencia y el certificado vencidos.", "Documentación", "Media", ["TRK-105"]),
    ("Retraso de 3 horas en la entrega de la ruta norte, carga del TRK-101.", "Logística", "Media", ["TRK-101"]),
    ("Accidente menor en el patio, un conductor herido del TRK-104.", "Seguridad", "Alta", ["TRK-104"]),
    ("Falta la firma del permiso de carga del TRK-102.", "Documentación", "Baja", ["TRK-102"]),
]

db = ia.conectar()
ahora = datetime.now()
for n, (placa, p, q, r, s, vence, hora) in enumerate(CAMIONES):
    A, E, pasos = reglas.evaluar(p, q, r, s, vence, hora)
    db.accesos.insert_one({"placa": placa, "fecha": ahora - timedelta(hours=n), "operador": "operador1",
                           "P": p, "Q": q, "R": r, "S": s, "A": A, "E": E, "explicacion": pasos})
    print(f"{placa}: {'AUTORIZADO' if A else 'DENEGADO'} | Inspección: {'SÍ' if E else 'NO'}")
for n, (correo, cat, prio, ents) in enumerate(INCIDENTES):
    db.incidentes.insert_one({"correo": correo, "estado": "nuevo", "fecha": ahora - timedelta(hours=n),
                              "clasificacion": {"categoria": cat, "prioridad": prio, "requiere_revision_humana": False},
                              "datos_extraidos": {"entidades": ents, "resumen": correo}})
    print(f"Incidente {cat}/{prio}: {correo[:50]}")
