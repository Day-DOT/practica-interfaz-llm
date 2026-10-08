"""Motor de reglas (lógica proposicional).

P = autorización previa, Q = peso excedido, R = materiales peligrosos, S = certificación vigente.
A = P y S y no Q        (ingreso autorizado)
E = P y (R o Q)         (inspección requerida)
Regla V: si la certificación está vencida por fecha -> A = False y E = True
Regla H: si hay materiales peligrosos (R) fuera de horario -> A = False
"""
from datetime import date


def evaluar(P, Q, R, S, vence=None, hora=12, inicio=6, fin=18):
    """Devuelve (A, E, explicacion). `vence` es un date o None; `hora` es un entero 0-23."""
    A = P and S and not Q
    E = P and (R or Q)
    pasos = [f"Base: A = P y S y no Q = {A}",
             f"Base: E = P y (R o Q) = {E}"]
    if E:
        pasos.append("Motivo de la inspección: " + " y ".join(
            texto for activo, texto in ((R, "R (materiales peligrosos)"), (Q, "Q (peso excedido)")) if activo))

    if vence is None or vence < date.today():           # Regla V (sin fecha = vencida)
        A, E = False, True
        pasos.append("Regla V: certificación vencida -> A = False y E = True")
    else:
        pasos.append("Regla V: certificación vigente, no cambia nada")

    if R and not (inicio <= hora <= fin):               # Regla H
        A = False
        pasos.append(f"Regla H: materiales peligrosos a las {hora}h (fuera de {inicio}-{fin}h) -> A = False")
    else:
        pasos.append("Regla H: no aplica")

    pasos.append(f"Resultado final: ingreso {'AUTORIZADO' if A else 'DENEGADO'}, "
                 f"inspección {'REQUERIDA' if E else 'no requerida'}")
    return bool(A), bool(E), pasos
