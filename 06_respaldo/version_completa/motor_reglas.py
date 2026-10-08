"""
motor_reglas.py
===============
Motor de reglas proposicionales para el control de acceso de camiones.

Premisas (las mismas del ``logica.py`` original de la práctica):
    P : Autorización previa.
    Q : Peso excedido.
    R : Carga de materiales peligrosos.
    S : Certificación vigente (lo que reporta el lector de certificación).

Reglas base:
    A = P ∧ S ∧ ¬Q      -> Ingreso autorizado
    E = P ∧ (R ∨ Q)     -> Inspección requerida

Reglas extendidas (se aplican en orden V -> H sobre el resultado base):
    Regla V: certificación vencida según su fecha de vencimiento -> A = False y E = True
    Regla H: materiales peligrosos (R) fuera del horario permitido -> A = False

Funciones:
    * ``calcular_AE``: lógica booleana pura (la usa el simulador de la GUI).
    * ``evaluar_acceso``: evaluación completa con explicación paso a paso.
    * Tablas de verdad de las reglas base, de V, de H y de la regla extendida completa.
    * ``analizar_reglas``: detección de redundancias y conflictos entre reglas.
"""

from __future__ import annotations

from datetime import date, datetime, time
from itertools import product
from typing import Any, Optional, Union

import config

FechaLike = Union[date, datetime]

#: Significado de cada premisa (fuente única para la GUI).
PREMISAS: dict[str, str] = {
    "P": "Autorización previa",
    "Q": "Peso excedido",
    "R": "Materiales peligrosos",
    "S": "Certificación vigente",
}

#: Descripción y justificación de las reglas extendidas (para la GUI y el informe).
REGLAS_EXTENDIDAS: dict[str, dict[str, str]] = {
    "V": {
        "nombre": "Vigencia de la certificación del conductor",
        "formula": "V = certificación vencida (por fecha)  =>  A = False  y  E = True",
        "justificacion": (
            "S es lo que reporta el lector en la caseta; V contrasta la fecha de vencimiento "
            "registrada en el sistema. Un conductor sin certificación vigente no puede operar "
            "legalmente: se niega el ingreso (A = False) y se exige inspección (E = True) para "
            "verificar la situación, aunque las demás premisas sean favorables."
        ),
    },
    "H": {
        "nombre": "Horario restringido para materiales peligrosos",
        "formula": "H = R (peligrosos) y fuera de horario  =>  A = False",
        "justificacion": (
            "Los materiales peligrosos solo deben ingresar cuando hay personal de seguridad y "
            "atención a emergencias. Fuera de ese horario se niega el ingreso (A = False); no "
            "cambia E porque la inspección depende del riesgo, no de la hora."
        ),
    },
}


# --------------------------------------------------------------------------- #
# Lógica pura
# --------------------------------------------------------------------------- #
def calcular_AE(
    P: bool, Q: bool, R: bool, S: bool,
    cert_vencida: bool = False, fuera_horario: bool = False,
) -> tuple[bool, bool]:
    """Calcula ``(A, E)`` aplicando reglas base y extendidas (V y luego H).

    Args:
        P, Q, R, S: Premisas base.
        cert_vencida: Regla V activada (certificación vencida por fecha).
        fuera_horario: El ingreso es fuera del horario; la regla H solo actúa si ``R``.
    """
    A = bool(P and S and not Q)
    E = bool(P and (R or Q))
    if cert_vencida:
        A, E = False, True
    if R and fuera_horario:
        A = False
    return A, E


def _bin(valor: bool) -> int:
    return 1 if valor else 0


def tabla_verdad_base() -> tuple[list[str], list[tuple[int, ...]]]:
    """Tabla de verdad de las reglas base: columnas ``P Q R S A E`` (16 filas)."""
    filas = []
    for P, Q, R, S in product((False, True), repeat=4):
        A, E = calcular_AE(P, Q, R, S)
        filas.append((_bin(P), _bin(Q), _bin(R), _bin(S), _bin(A), _bin(E)))
    return ["P", "Q", "R", "S", "A", "E"], filas


def tabla_verdad_regla(nombre: str) -> tuple[list[str], list[tuple[int, ...]]]:
    """Tabla de verdad de una regla extendida respecto al resultado previo.

    * ``"V"``: columnas ``V A_base E_base A_final E_final`` (8 filas).
    * ``"H"``: columnas ``R F A_previo A_final`` (8 filas; ``F`` = fuera de horario).

    Raises:
        ValueError: Si ``nombre`` no es ``"V"`` ni ``"H"``.
    """
    if nombre == "V":
        filas = []
        for V, A0, E0 in product((False, True), repeat=3):
            A1, E1 = (False, True) if V else (A0, E0)
            filas.append((_bin(V), _bin(A0), _bin(E0), _bin(A1), _bin(E1)))
        return ["V", "A_base", "E_base", "A_final", "E_final"], filas
    if nombre == "H":
        filas = []
        for R, F, A0 in product((False, True), repeat=3):
            filas.append((_bin(R), _bin(F), _bin(A0), _bin(A0 and not (R and F))))
        return ["R", "F", "A_previo", "A_final"], filas
    raise ValueError("La regla debe ser 'V' o 'H'.")


def tabla_verdad_extendida() -> tuple[list[str], list[tuple[int, ...]]]:
    """Tabla completa (64 filas): columnas ``P Q R S V F A E``."""
    filas = []
    for P, Q, R, S, V, F in product((False, True), repeat=6):
        A, E = calcular_AE(P, Q, R, S, V, F)
        filas.append((_bin(P), _bin(Q), _bin(R), _bin(S), _bin(V), _bin(F), _bin(A), _bin(E)))
    return ["P", "Q", "R", "S", "V", "F", "A", "E"], filas


def analizar_reglas() -> dict[str, Any]:
    """Detecta redundancias y conflictos entre las reglas (reto opcional).

    Recorre las 64 combinaciones de (P, Q, R, S, V, F) y mide qué aporta cada regla.

    Returns:
        Diccionario con ``contradicciones`` y ``texto`` (lista de líneas legibles).
    """
    total = impacto_v = impacto_h = h_redundante = conflictos = 0
    contradicciones: list[str] = []

    for P, Q, R, S, V, F in product((False, True), repeat=6):
        total += 1
        a0, e0 = calcular_AE(P, Q, R, S)
        a1, e1 = calcular_AE(P, Q, R, S, V, False)
        a2, _ = calcular_AE(P, Q, R, S, V, F)

        if (a1, e1) != (a0, e0):
            impacto_v += 1
            conflictos += 1  # V contradice el resultado base y se resuelve por precedencia
        if a2 != a1:
            impacto_h += 1
        if R and F and a1 is False:
            h_redundante += 1
        if (V or (R and F)) and a2:  # autorizado a pesar de V o H activas
            contradicciones.append(f"P={_bin(P)} Q={_bin(Q)} R={_bin(R)} S={_bin(S)} V={_bin(V)} F={_bin(F)}")

    texto = [
        f"Combinaciones analizadas (P,Q,R,S,V,F): {total}.",
        f"Regla V modifica el resultado base en {impacto_v} combinaciones "
        f"({'aporta valor' if impacto_v else 'REDUNDANTE'}).",
        f"Regla H cambia A (después de V) en {impacto_h} combinaciones "
        f"({'aporta valor' if impacto_h else 'REDUNDANTE'}).",
        f"Regla H es redundante en {h_redundante} combinaciones donde A ya era Falso "
        "(p. ej. si V está activa o el resultado base ya negaba el ingreso).",
        f"Conflictos entre V y la regla base resueltos por precedencia (V prevalece): {conflictos}.",
        "Contradicciones (ingreso autorizado con V o H activas): "
        + ("ninguna." if not contradicciones else f"{len(contradicciones)} -> revisar."),
        "Orden de evaluación: base -> V -> H. Con ese orden, V y H nunca pueden autorizar el ingreso.",
    ]
    return {"contradicciones": contradicciones, "texto": texto}


# --------------------------------------------------------------------------- #
# Evaluación completa con explicación
# --------------------------------------------------------------------------- #
def _si_no(valor: bool) -> str:
    """Representa un booleano como 'Verdadero'/'Falso' para las explicaciones."""
    return "Verdadero" if valor else "Falso"


def _como_fecha(valor: FechaLike) -> date:
    return valor.date() if isinstance(valor, datetime) else valor


def _en_horario(hora: time, inicio: time, fin: time) -> bool:
    """Indica si ``hora`` está dentro de [inicio, fin]; admite rangos que cruzan medianoche."""
    if inicio <= fin:
        return inicio <= hora <= fin
    return hora >= inicio or hora <= fin


def evaluar_acceso(
    P: bool,
    Q: bool,
    R: bool,
    S: bool,
    vigencia_certificacion: Optional[FechaLike] = None,
    hora_ingreso: Optional[Union[time, datetime]] = None,
    fecha_evaluacion: Optional[FechaLike] = None,
    horario_permitido: Optional[tuple[time, time]] = None,
) -> dict[str, Any]:
    """Evalúa si un camión puede ingresar y si requiere inspección.

    Args:
        P: Autorización previa.
        Q: Peso excedido.
        R: Materiales peligrosos.
        S: Certificación vigente (según el lector).
        vigencia_certificacion: Fecha de vencimiento de la certificación del conductor.
            Si es ``None`` no se puede verificar y se considera vencida (criterio conservador).
        hora_ingreso: Hora (o ``datetime``) del ingreso. Si es ``None`` se usa la actual.
        fecha_evaluacion: Fecha de referencia para la vigencia. Por defecto hoy.
        horario_permitido: ``(inicio, fin)`` para materiales peligrosos. Por defecto el de ``config``.

    Returns:
        Diccionario con ``A``, ``E``, ``reglas_aplicadas`` y ``explicacion`` (lista de pasos).
    """
    explicacion: list[str] = []
    reglas_aplicadas: list[str] = []
    P, Q, R, S = bool(P), bool(Q), bool(R), bool(S)

    explicacion.append(
        "Paso 1 - Premisas: "
        f"P (autorización previa) = {_si_no(P)}, Q (peso excedido) = {_si_no(Q)}, "
        f"R (materiales peligrosos) = {_si_no(R)}, S (certificación vigente) = {_si_no(S)}."
    )

    # --- Paso 2: regla base A = P ∧ S ∧ ¬Q ---------------------------------
    A, E = calcular_AE(P, Q, R, S)
    explicacion.append(
        f"Paso 2 - Regla base A = P ∧ S ∧ ¬Q: {_si_no(P)} ∧ {_si_no(S)} ∧ ¬{_si_no(Q)} = {_si_no(A)} "
        f"(ingreso {'autorizado' if A else 'no autorizado'})."
    )
    if not A:
        motivos = []
        if not P:
            motivos.append("P es Falso (sin autorización previa)")
        if not S:
            motivos.append("S es Falso (certificación no vigente)")
        if Q:
            motivos.append("Q es Verdadero (peso excedido)")
        explicacion.append("         Motivo(s) del rechazo base: " + "; ".join(motivos) + ".")

    # --- Paso 3: regla base E = P ∧ (R ∨ Q) --------------------------------
    explicacion.append(
        f"Paso 3 - Regla base E = P ∧ (R ∨ Q): {_si_no(P)} ∧ ({_si_no(R)} ∨ {_si_no(Q)}) = {_si_no(E)} "
        f"(inspección {'requerida' if E else 'no requerida'})."
    )
    if E:
        causas = []
        if R:
            causas.append("R es Verdadero (materiales peligrosos)")
        if Q:
            causas.append("Q es Verdadero (peso excedido)")
        explicacion.append("         Motivo(s) de la inspección: " + "; ".join(causas) + ".")

    # --- Paso 4: Regla V (vigencia de certificación por fecha) -------------
    referencia = _como_fecha(fecha_evaluacion) if fecha_evaluacion else date.today()
    if vigencia_certificacion is None:
        certificacion_vencida = True
        explicacion.append(
            "Paso 4 - Regla V: no se informó fecha de vencimiento de la certificación; "
            "se considera VENCIDA por criterio conservador."
        )
    else:
        vence = _como_fecha(vigencia_certificacion)
        certificacion_vencida = vence < referencia
        explicacion.append(
            f"Paso 4 - Regla V: certificación vence el {vence.isoformat()}, fecha de evaluación "
            f"{referencia.isoformat()} -> {'VENCIDA' if certificacion_vencida else 'vigente'}."
        )
    if certificacion_vencida:
        A, E = False, True
        reglas_aplicadas.append("V")
        explicacion.append("         Regla V activada: A = Falso y E = Verdadero (sobrescribe el resultado base).")
    else:
        explicacion.append("         Regla V no activada: no modifica A ni E.")

    # --- Paso 5: Regla H (horario para materiales peligrosos) --------------
    if not R:
        explicacion.append("Paso 5 - Regla H: la carga no es de materiales peligrosos (R = Falso); no aplica horario.")
    else:
        if hora_ingreso is None:
            hora = datetime.now().time()
        else:
            hora = hora_ingreso.time() if isinstance(hora_ingreso, datetime) else hora_ingreso
        inicio, fin = horario_permitido or config.horario_peligrosos()
        fuera_horario = not _en_horario(hora, inicio, fin)
        explicacion.append(
            f"Paso 5 - Regla H: materiales peligrosos, ingreso a las {hora.strftime('%H:%M')}, horario permitido "
            f"{inicio.strftime('%H:%M')}-{fin.strftime('%H:%M')} -> "
            f"{'FUERA de horario' if fuera_horario else 'dentro de horario'}."
        )
        if fuera_horario:
            A = False
            reglas_aplicadas.append("H")
            explicacion.append("         Regla H activada: A = Falso.")
        else:
            explicacion.append("         Regla H no activada: no modifica A.")

    explicacion.append(
        f"Paso 6 - Conclusión: Ingreso {'AUTORIZADO' if A else 'DENEGADO'}; "
        f"inspección {'REQUERIDA' if E else 'no requerida'}"
        + (f". Reglas extendidas aplicadas: {', '.join(reglas_aplicadas)}." if reglas_aplicadas
           else ". Sin reglas extendidas aplicadas.")
    )
    return {"A": A, "E": E, "reglas_aplicadas": reglas_aplicadas, "explicacion": explicacion}
