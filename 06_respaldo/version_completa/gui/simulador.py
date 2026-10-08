"""
gui/simulador.py
================
Simulador de tablas de verdad: el usuario activa interruptores (P, S, Q, R, V, H) y ve cómo
cambian A y E en vivo; se resalta la fila correspondiente de la tabla de verdad elegida.
Incluye la justificación de las reglas extendidas y el análisis de redundancias.
"""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

import motor_reglas as mr
from gui.comun import GRIS, NARANJA, ROJO, VERDE, PestanaBase, Tabla, solo_lectura

MODOS: dict[str, str] = {
    "Base (16 filas)": "base",
    "Regla V": "V",
    "Regla H": "H",
    "Extendida (64 filas)": "extendida",
}


class SimuladorTab(PestanaBase):
    """Interruptores en vivo + tabla de verdad con la fila actual resaltada."""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, app)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        izq = ctk.CTkFrame(self)
        izq.grid(row=0, column=0, sticky="ns", padx=(0, 8), pady=4)
        ctk.CTkLabel(izq, text="Interruptores", font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", padx=14, pady=(12, 6))
        self.switches: dict[str, ctk.CTkSwitch] = {}
        for clave, texto in (
            *((k, f"{k} - {v}") for k, v in mr.PREMISAS.items()),
            ("V", "V - Certificación vencida (por fecha)"), ("F", "F - Ingreso fuera del horario permitido"),
        ):
            sw = ctk.CTkSwitch(izq, text=texto, command=self._actualizar)
            sw.pack(anchor="w", padx=14, pady=5)
            self.switches[clave] = sw
        self.switches["P"].select()
        self.switches["S"].select()

        self.lbl_a = ctk.CTkLabel(izq, text="A", height=60, width=250, corner_radius=8, text_color="white",
                                  font=ctk.CTkFont(size=20, weight="bold"))
        self.lbl_a.pack(padx=14, pady=(14, 6))
        self.lbl_e = ctk.CTkLabel(izq, text="E", height=60, width=250, corner_radius=8, text_color="white",
                                  font=ctk.CTkFont(size=20, weight="bold"))
        self.lbl_e.pack(padx=14, pady=6)
        self.lbl_formulas = ctk.CTkLabel(izq, text="", justify="left", anchor="w", wraplength=250,
                                         font=ctk.CTkFont(family="Consolas", size=12))
        self.lbl_formulas.pack(anchor="w", padx=14, pady=(8, 14))

        der = ctk.CTkFrame(self)
        der.grid(row=0, column=1, sticky="nsew", pady=4)
        der.grid_columnconfigure(0, weight=1)
        der.grid_rowconfigure(1, weight=3)
        der.grid_rowconfigure(3, weight=2)

        barra = ctk.CTkFrame(der, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 4))
        ctk.CTkLabel(barra, text="Tabla de verdad:", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.selector = ctk.CTkSegmentedButton(barra, values=list(MODOS), command=lambda _v: self._cambiar_modo())
        self.selector.set("Base (16 filas)")
        self.selector.pack(side="left", padx=10)

        self.tabla = Tabla(der, [("x", "-", 60)], altura=10)
        self.tabla.grid(row=1, column=0, sticky="nsew", padx=10)
        self._cache_filas: list[tuple[int, ...]] = []

        ctk.CTkLabel(der, text="Justificación de las reglas y análisis de redundancias",
                     font=ctk.CTkFont(weight="bold")).grid(row=2, column=0, sticky="w", padx=12, pady=(10, 0))
        self.txt_info = ctk.CTkTextbox(der, wrap="word", state="disabled", height=150)
        self.txt_info.grid(row=3, column=0, sticky="nsew", padx=10, pady=(2, 10))
        self._rellenar_info()
        self._cambiar_modo()

    def al_mostrar(self) -> None:
        self._actualizar()

    # ------------------------------------------------------------------ #
    def _entradas(self) -> dict[str, bool]:
        return {k: bool(sw.get()) for k, sw in self.switches.items()}

    def _actualizar(self) -> None:
        e = self._entradas()
        A, E = mr.calcular_AE(e["P"], e["Q"], e["R"], e["S"], e["V"], e["F"])
        A0, E0 = mr.calcular_AE(e["P"], e["Q"], e["R"], e["S"])
        self.lbl_a.configure(text=f"A (ingreso) = {int(A)}   {'AUTORIZADO' if A else 'DENEGADO'}",
                             fg_color=VERDE if A else ROJO)
        self.lbl_e.configure(text=f"E (inspección) = {int(E)}   {'REQUERIDA' if E else 'no requerida'}",
                             fg_color=NARANJA if E else GRIS)
        b = {k: int(v) for k, v in e.items()}
        self.lbl_formulas.configure(
            text=(f"A base = P∧S∧¬Q = {b['P']}∧{b['S']}∧¬{b['Q']} = {int(A0)}\n"
                  f"E base = P∧(R∨Q) = {b['P']}∧({b['R']}∨{b['Q']}) = {int(E0)}\n"
                  f"Regla V: {'ACTIVA (A=0, E=1)' if e['V'] else 'inactiva'}\n"
                  f"Regla H: {'ACTIVA (R y fuera de horario: A=0)' if e['R'] and e['F'] else 'inactiva'}\n"
                  f"Resultado final: A={int(A)}, E={int(E)}"))
        self._resaltar()

    def _cambiar_modo(self) -> None:
        modo = MODOS[self.selector.get()]
        if modo == "base":
            cabeceras, filas = mr.tabla_verdad_base()
        elif modo == "extendida":
            cabeceras, filas = mr.tabla_verdad_extendida()
        else:
            cabeceras, filas = mr.tabla_verdad_regla(modo)
        self._cache_filas = filas
        self.tabla.reconfigurar([(h, h, 70) for h in cabeceras])
        ids = [str(n) for n in range(len(filas))]
        self.tabla.cargar([tuple("1" if v else "0" for v in f) for f in filas], ids)
        self._resaltar()

    def _resaltar(self) -> None:
        """Selecciona la fila cuyas entradas coinciden con los interruptores actuales."""
        modo = MODOS[self.selector.get()]
        e = {k: int(v) for k, v in self._entradas().items()}
        A0, E0 = mr.calcular_AE(bool(e["P"]), bool(e["Q"]), bool(e["R"]), bool(e["S"]))
        if modo == "base":
            clave = (e["P"], e["Q"], e["R"], e["S"])
        elif modo == "extendida":
            clave = (e["P"], e["Q"], e["R"], e["S"], e["V"], e["F"])
        elif modo == "V":
            clave = (e["V"], int(A0), int(E0))
        else:
            clave = (e["R"], e["F"], int(A0))
        for n, fila in enumerate(self._cache_filas):
            if fila[:len(clave)] == clave:
                self.tabla.seleccionar(str(n))
                return

    def _rellenar_info(self) -> None:
        partes = []
        for codigo, info in mr.REGLAS_EXTENDIDAS.items():
            partes.append(f"Regla {codigo} - {info['nombre']}\n  {info['formula']}\n  Justificación: "
                          f"{info['justificacion']}\n")
        partes.append("Análisis de reglas (reto opcional)\n" + "\n".join("  • " + t for t in mr.analizar_reglas()["texto"]))
        solo_lectura(self.txt_info, "\n".join(partes))
