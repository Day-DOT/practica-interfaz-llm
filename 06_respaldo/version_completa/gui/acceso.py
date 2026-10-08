"""
gui/acceso.py
=============
Control de acceso: formulario P/S/Q/R o búsqueda por placa, resultado en semáforo con la
explicación paso a paso, y bitácora de accesos (consulta y baja).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

import customtkinter as ctk
from tkinter import messagebox

import config
import repositorio
from gui.comun import (GRIS, NARANJA, ROJO, VERDE, PestanaBase, Semaforo, Tabla, parsear_fecha,
                       parsear_hora, solo_lectura)
from motor_reglas import PREMISAS, evaluar_acceso



class AccesoTab(PestanaBase):
    """Pestaña de evaluación de ingresos de camiones."""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._construir_formulario()
        self._construir_resultado()

    # ------------------------------------------------------------------ #
    def _construir_formulario(self) -> None:
        form = ctk.CTkScrollableFrame(self, width=330, label_text="Datos del ingreso")
        form.grid(row=0, column=0, sticky="ns", padx=(0, 8), pady=4)

        ctk.CTkLabel(form, text="Operador").pack(anchor="w", padx=6)
        self.ent_operador = ctk.CTkEntry(form, width=290)
        self.ent_operador.insert(0, config.get("operador"))
        self.ent_operador.pack(padx=6, pady=(0, 6))

        ctk.CTkLabel(form, text="Placa o ID del camión").pack(anchor="w", padx=6)
        fila = ctk.CTkFrame(form, fg_color="transparent")
        fila.pack(fill="x", padx=6, pady=(0, 2))
        self.ent_placa = ctk.CTkEntry(fila, width=200, placeholder_text="ABC-123 o CAM-101")
        self.ent_placa.pack(side="left")
        self.ent_placa.bind("<Return>", lambda _e: self._buscar_camion())
        self.btn_buscar = ctk.CTkButton(fila, text="Buscar", width=80, command=self._buscar_camion)
        self.btn_buscar.pack(side="left", padx=(8, 0))
        self.lbl_camion = ctk.CTkLabel(form, text="Escribe la placa y pulsa Buscar para cargar los datos "
                                                  "registrados.", wraplength=290, justify="left", text_color=GRIS)
        self.lbl_camion.pack(anchor="w", padx=6, pady=(0, 6))
        self._camion_id = ""

        self.switches: dict[str, ctk.CTkSwitch] = {}
        for clave, texto in PREMISAS.items():
            sw = ctk.CTkSwitch(form, text=f"{clave} - {texto}")
            sw.pack(anchor="w", padx=6, pady=4)
            self.switches[clave] = sw
        self.switches["P"].select()
        self.switches["S"].select()

        ctk.CTkLabel(form, text="Vencimiento certificación conductor (AAAA-MM-DD)").pack(anchor="w", padx=6, pady=(6, 0))
        self.ent_vigencia = ctk.CTkEntry(form, width=290)
        self.ent_vigencia.insert(0, (date.today() + timedelta(days=365)).isoformat())
        self.ent_vigencia.pack(padx=6)
        ctk.CTkLabel(form, text="Hora de ingreso (HH:MM)").pack(anchor="w", padx=6, pady=(6, 0))
        self.ent_hora = ctk.CTkEntry(form, width=290)
        self.ent_hora.insert(0, datetime.now().strftime("%H:%M"))
        self.ent_hora.pack(padx=6, pady=(0, 10))

        self.btn_evaluar = ctk.CTkButton(form, text="Evaluar y registrar", height=36, command=self._evaluar)
        self.btn_evaluar.pack(fill="x", padx=6, pady=(4, 4))
        self.lbl_estado = ctk.CTkLabel(form, text="", wraplength=290, justify="left")
        self.lbl_estado.pack(anchor="w", padx=6, pady=(0, 8))

    def _construir_resultado(self) -> None:
        der = ctk.CTkFrame(self)
        der.grid(row=0, column=1, sticky="nsew", pady=4)
        der.grid_columnconfigure(1, weight=1)
        der.grid_rowconfigure(1, weight=2)
        der.grid_rowconfigure(3, weight=2)

        self.semaforo = Semaforo(der, 150)
        self.semaforo.grid(row=0, column=0, rowspan=2, padx=14, pady=12, sticky="n")
        marco = ctk.CTkFrame(der, fg_color="transparent")
        marco.grid(row=0, column=1, sticky="ew", pady=(12, 0))
        self.lbl_decision = ctk.CTkLabel(marco, text="Sin evaluar", font=ctk.CTkFont(size=24, weight="bold"),
                                         anchor="w")
        self.lbl_decision.pack(anchor="w")
        self.lbl_detalle = ctk.CTkLabel(marco, text="A (ingreso) y E (inspección) aparecerán aquí.",
                                        text_color=GRIS, anchor="w")
        self.lbl_detalle.pack(anchor="w")

        self.txt_explicacion = ctk.CTkTextbox(der, wrap="word", state="disabled")
        self.txt_explicacion.grid(row=1, column=1, sticky="nsew", padx=(0, 12), pady=(6, 6))

        barra = ctk.CTkFrame(der, fg_color="transparent")
        barra.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12)
        ctk.CTkLabel(barra, text="Bitácora de accesos recientes", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkButton(barra, text="Eliminar seleccionado", width=150, fg_color=ROJO, command=self._eliminar).pack(
            side="right")
        ctk.CTkButton(barra, text="Actualizar", width=90, command=self.cargar_historial).pack(side="right", padx=6)

        self.tabla = Tabla(der, [
            ("fecha", "Fecha", 130), ("placa", "Placa", 80), ("operador", "Operador", 90),
            ("P", "P", 30), ("Q", "Q", 30), ("R", "R", 30), ("S", "S", 30),
            ("A", "Ingreso", 80), ("E", "Inspección", 80),
        ], altura=7, al_seleccionar=self._mostrar_seleccion)
        self.tabla.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=12, pady=(2, 12))
        self._accesos: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ #
    def al_mostrar(self) -> None:
        if self.app.db is not None:
            self.cargar_historial()

    def al_conectar(self) -> None:
        self.cargar_historial()

    def _buscar_camion(self) -> None:
        clave = self.ent_placa.get().strip()
        if not clave:
            messagebox.showwarning("Búsqueda", "Escribe una placa o ID de camión.")
            return
        db = self.app.db_o_aviso()
        if db is None:
            return
        self.btn_buscar.configure(state="disabled")
        self.lbl_camion.configure(text="Buscando...", text_color=NARANJA)

        def exito(camion: Optional[dict[str, Any]]) -> None:
            self.btn_buscar.configure(state="normal")
            if camion is None:
                self._camion_id = ""
                self.lbl_camion.configure(
                    text="Camión no registrado. Puedes evaluar igualmente o darlo de alta en la pestaña Camiones.",
                    text_color=NARANJA)
                return
            self._camion_id = camion.get("camion_id", "")
            cert = camion.get("certificacion_conductor", {})
            vigencia = cert.get("vigencia")
            self.ent_placa.delete(0, "end")
            self.ent_placa.insert(0, camion["placa"])
            if vigencia:
                self.ent_vigencia.delete(0, "end")
                self.ent_vigencia.insert(0, vigencia.date().isoformat())
            if camion.get("autorizacion"):
                self.switches["P"].select()
            else:
                self.switches["P"].deselect()
            self.lbl_camion.configure(
                text=f"{self._camion_id} · {camion.get('empresa', '')}\nConductor: {cert.get('conductor', '-')}\n"
                     f"Autorizado: {'sí' if camion.get('autorizacion') else 'NO'} (se ajustó P)",
                text_color=VERDE if camion.get("autorizacion") else NARANJA)

        def error(exc: Exception) -> None:
            self.btn_buscar.configure(state="normal")
            self.lbl_camion.configure(text=f"Error: {exc}", text_color=ROJO)

        self.app.ejecutar(lambda: repositorio.buscar_camion(db, clave), exito, error)

    def _leer_entradas(self) -> dict[str, Any]:
        """Valida el formulario.

        Raises:
            ValueError: Con un mensaje claro si algún campo es inválido.
        """
        placa = self.ent_placa.get().strip().upper()
        if not placa:
            raise ValueError("Ingresa la placa del camión.")
        operador = self.ent_operador.get().strip()
        if not operador:
            raise ValueError("Ingresa el nombre del operador.")
        return {
            "placa": placa, "operador": operador,
            "vigencia": parsear_fecha(self.ent_vigencia.get(), "La fecha de vencimiento"),
            "hora": parsear_hora(self.ent_hora.get()),
            "premisas": {k: bool(sw.get()) for k, sw in self.switches.items()},
        }

    def _evaluar(self) -> None:
        try:
            datos = self._leer_entradas()
        except ValueError as exc:
            messagebox.showwarning("Datos incompletos", str(exc))
            return
        p = datos["premisas"]
        try:
            resultado = evaluar_acceso(
                P=p["P"], Q=p["Q"], R=p["R"], S=p["S"], vigencia_certificacion=datos["vigencia"],
                hora_ingreso=datos["hora"])
        except Exception as exc:
            self.app.mostrar_error("Motor de reglas", exc)
            return
        self._mostrar_resultado(resultado)
        self._guardar(datos, resultado)

    def _mostrar_resultado(self, r: dict[str, Any]) -> None:
        if not r["A"]:
            self.semaforo.establecer("rojo")
            titulo = "INGRESO DENEGADO"
        elif r["E"]:
            self.semaforo.establecer("amarillo")
            titulo = "AUTORIZADO CON INSPECCIÓN"
        else:
            self.semaforo.establecer("verde")
            titulo = "INGRESO AUTORIZADO"
        self.lbl_decision.configure(text=titulo)
        self.lbl_detalle.configure(
            text=f"A (ingreso) = {r['A']}   ·   E (inspección) = {r['E']}   ·   "
                 f"Reglas extendidas: {', '.join(r['reglas_aplicadas']) or 'ninguna'}")
        solo_lectura(self.txt_explicacion, "\n".join(r["explicacion"]))

    def _guardar(self, datos: dict[str, Any], resultado: dict[str, Any]) -> None:
        db = self.app.db
        if db is None:
            self.lbl_estado.configure(text="Evaluado, pero NO guardado: sin conexión a MongoDB.", text_color=ROJO)
            return
        self.btn_evaluar.configure(state="disabled")
        self.lbl_estado.configure(text="Guardando en la bitácora...", text_color=NARANJA)
        camion_id = self._camion_id

        def trabajo() -> str:
            return repositorio.registrar_acceso(
                db, placa=datos["placa"], camion_id=camion_id, operador=datos["operador"],
                premisas=datos["premisas"], resultado=resultado,
                vigencia=datos["vigencia"], hora_ingreso=datos["hora"].strftime("%H:%M"))

        def exito(_: Any) -> None:
            self.btn_evaluar.configure(state="normal")
            self.lbl_estado.configure(text="Decisión guardada en la bitácora.", text_color=VERDE)
            self.cargar_historial()

        def error(exc: Exception) -> None:
            self.btn_evaluar.configure(state="normal")
            self.lbl_estado.configure(text=f"Error al guardar: {exc}", text_color=ROJO)

        self.app.ejecutar(trabajo, exito, error)

    # ------------------------------------------------------------------ #
    def cargar_historial(self) -> None:
        db = self.app.db
        if db is None:
            return

        def exito(accesos: list[dict[str, Any]]) -> None:
            self._accesos = {str(a["_id"]): a for a in accesos}
            si = lambda v: "Sí" if v else "No"  # noqa: E731
            self.tabla.cargar(
                [(a["fecha"].strftime("%Y-%m-%d %H:%M"), a.get("placa", ""), a.get("operador", ""),
                  si(a.get("P")), si(a.get("Q")), si(a.get("R")), si(a.get("S")),
                  "Autorizado" if a.get("A") else "Denegado", si(a.get("E"))) for a in accesos],
                ids=list(self._accesos))

        self.app.ejecutar(lambda: repositorio.listar_accesos(db, limite=100), exito,
                          lambda exc: self.lbl_estado.configure(text=f"Error al leer la bitácora: {exc}",
                                                                text_color=ROJO))

    def _mostrar_seleccion(self) -> None:
        iid = self.tabla.seleccionado()
        acceso = self._accesos.get(iid or "")
        if acceso:
            solo_lectura(self.txt_explicacion, "\n".join(acceso.get("explicacion", [])))

    def _eliminar(self) -> None:
        iid = self.tabla.seleccionado()
        db = self.app.db_o_aviso()
        if not iid or db is None:
            if db is not None:
                messagebox.showinfo("Eliminar", "Selecciona un registro de la bitácora.")
            return
        if not messagebox.askyesno("Eliminar", "¿Eliminar el registro seleccionado de la bitácora?"):
            return
        self.app.ejecutar(lambda: repositorio.eliminar_acceso(db, iid), lambda _: self.cargar_historial(),
                          lambda exc: self.app.mostrar_error("Eliminar acceso", exc))
