"""Agrega 4 registros de camiones a la bitácora (colección accesos). Ejecutar: python camiones_demo.py"""
from datetime import date, datetime

import ia
import reglas

# placa, P, Q, R, S, vence, hora
CAMIONES = [
    ("ABC-123", True, False, False, True, date(2027, 6, 30), 10),    # autorizado, sin inspección
    ("XYZ-789", True, True, False, True, date(2027, 3, 15), 14),     # peso excedido -> inspección
    ("LMN-456", True, False, True, True, date(2027, 1, 20), 22),     # peligrosos fuera de horario
    ("DEF-321", True, False, False, True, date(2025, 12, 1), 9),     # certificación vencida
]

db = ia.conectar()
for placa, p, q, r, s, vence, hora in CAMIONES:
    A, E, pasos = reglas.evaluar(p, q, r, s, vence, hora)
    db.accesos.insert_one({"placa": placa, "fecha": datetime.now(), "operador": "operador1",
                           "P": p, "Q": q, "R": r, "S": s, "A": A, "E": E, "explicacion": pasos})
    print(f"{placa}: {'AUTORIZADO' if A else 'DENEGADO'} | Inspección: {'SÍ' if E else 'NO'}")
