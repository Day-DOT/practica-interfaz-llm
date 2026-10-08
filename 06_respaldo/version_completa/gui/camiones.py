"""
gui/camiones.py
===============
CRUD de la colección ``camiones``: alta, consulta (con búsqueda), edición y baja.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import customtkinter as ctk
from tkinter import messagebox

import repositorio
from gui.comun import GRIS, NARANJA, ROJO, VERDE, PestanaBase, Tabla, parsear_fecha


class CamionesTab(PestanaBase):
    """Gestión de camiones registrados."""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, app)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._id_actual: Optional[str] = None
        self._camiones: dict[str, dict[str, Any]] = {}

        form = ctk.CTkFrame(self)
        form.grid(row=0, column=0, sticky="ns", padx=(0, 8), pady=4)
        ctk.CTkLabel(form, text="Datos del camión", font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", padx=14, pady=(12, 6))
        self.campos: dict[str, ctk.CTkEntry] = {}
        for clave, etiqueta, ejemplo in (
            ("placa", "Placa", "ABC-123"), ("camion_id", "ID del camión", "CAM-101"),
            ("empresa", "Empresa", "TransNorte SA"), ("conductor", "Conductor", "Juan Pérez"),
            ("vigencia", "Vencimiento certificación (AAAA-MM-DD)", ""),
        ):
            ctk.CTkLabel(form, text=etiqueta).pack(anchor="w", padx=14)
            ent = ctk.CTkEntry(form, width=270, placeholder_text=ejemplo)
            ent.pack(padx=14, pady=(0, 6))
            self.campos[clave] = ent
        self.sw_autorizado = ctk.CTkSwitch(form, text="Camión autorizado")
        self.sw_autorizado.select()
        self.sw_autorizado.pack(anchor="w", padx=14, pady=6)

        self.btn_guardar = ctk.CTkButton(form, text="Crear camión", command=self._guardar)
        self.btn_guardar.pack(fill="x", padx=14, pady=(8, 4))
        ctk.CTkButton(form, text="Nuevo / limpiar", fg_color=GRIS, command=self._limpiar).pack(fill="x", padx=14, pady=4)
        ctk.CTkButton(form, text="Eliminar", fg_color=ROJO, command=self._eliminar).pack(fill="x", padx=14, pady=4)
        self.lbl_estado = ctk.CTkLabel(form, text="", wraplength=270, justify="left")
        self.lbl_estado.pack(anchor="w", padx=14, pady=(6, 12))

        der = ctk.CTkFrame(self)
        der.grid(row=0, column=1, sticky="nsew", pady=4)
        der.grid_columnconfigure(0, weight=1)
        der.grid_rowconfigure(1, weight=1)
        barra = ctk.CTkFrame(der, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        self.ent_buscar = ctk.CTkEntry(barra, width=260, placeholder_text="Buscar por placa, ID o empresa")
        self.ent_buscar.pack(side="left")
        self.ent_buscar.bind("<Return>", lambda _e: self.cargar())
        ctk.CTkButton(barra, text="Buscar", width=80, command=self.cargar).pack(side="left", padx=8)
        ctk.CTkButton(barra, text="Ver todos", width=80, fg_color=GRIS,
                      command=lambda: (self.ent_buscar.delete(0, "end"), self.cargar())).pack(side="left")
        self.tabla = Tabla(der, [
            ("placa", "Placa", 90), ("camion_id", "ID", 80), ("empresa", "Empresa", 150),
            ("auth", "Autorizado", 80), ("conductor", "Conductor", 130), ("vigencia", "Certif. vence", 100),
        ], altura=14, al_seleccionar=self._al_seleccionar)
        self.tabla.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

    def al_mostrar(self) -> None:
        if self.app.db is not None:
            self.cargar()

    def al_conectar(self) -> None:
        self.cargar()

    def cargar(self) -> None:
        db = self.app.db_o_aviso()
        if db is None:
            return
        texto = self.ent_buscar.get()

        def exito(camiones: list[dict[str, Any]]) -> None:
            self._camiones = {str(c["_id"]): c for c in camiones}
            hoy = datetime.now()
            filas = []
            for c in camiones:
                cert = c.get("certificacion_conductor", {})
                v = cert.get("vigencia")
                filas.append((c["placa"], c.get("camion_id", ""), c.get("empresa", ""),
                              "Sí" if c.get("autorizacion") else "No", cert.get("conductor", ""),
                              (v.date().isoformat() + (" (vencida)" if v < hoy else "")) if v else "-"))
            self.tabla.cargar(filas, list(self._camiones))
            self.lbl_estado.configure(text=f"{len(camiones)} camión(es).", text_color=GRIS)

        self.app.ejecutar(lambda: repositorio.listar_camiones(db, texto), exito,
                          lambda exc: self.lbl_estado.configure(text=f"Error: {exc}", text_color=ROJO))

    def _al_seleccionar(self) -> None:
        iid = self.tabla.seleccionado()
        camion = self._camiones.get(iid or "")
        if not camion:
            return
        self._id_actual = iid
        cert = camion.get("certificacion_conductor", {})
        valores = {"placa": camion["placa"], "camion_id": camion.get("camion_id", ""),
                   "empresa": camion.get("empresa", ""), "conductor": cert.get("conductor", ""),
                   "vigencia": cert["vigencia"].date().isoformat() if cert.get("vigencia") else ""}
        for clave, ent in self.campos.items():
            ent.delete(0, "end")
            ent.insert(0, valores[clave])
        (self.sw_autorizado.select if camion.get("autorizacion") else self.sw_autorizado.deselect)()
        self.btn_guardar.configure(text="Guardar cambios")

    def _limpiar(self) -> None:
        self._id_actual = None
        for ent in self.campos.values():
            ent.delete(0, "end")
        self.sw_autorizado.select()
        self.btn_guardar.configure(text="Crear camión")
        self.tabla.quitar_seleccion()

    def _leer(self) -> dict[str, Any]:
        """Lee y valida el formulario.

        Raises:
            ValueError: Con mensaje claro si algo es inválido.
        """
        datos = {k: e.get().strip() for k, e in self.campos.items()}
        datos["vigencia"] = parsear_fecha(datos["vigencia"], "El vencimiento de la certificación")
        datos["autorizacion"] = bool(self.sw_autorizado.get())
        repositorio.validar_camion(datos)  # valida ahora para avisar antes de ir a la base
        return datos

    def _guardar(self) -> None:
        try:
            datos = self._leer()
        except ValueError as exc:
            messagebox.showwarning("Datos inválidos", str(exc))
            return
        db = self.app.db_o_aviso()
        if db is None:
            return
        id_actual = self._id_actual
        self.btn_guardar.configure(state="disabled")
        self.lbl_estado.configure(text="Guardando...", text_color=NARANJA)

        def trabajo() -> str:
            if id_actual:
                repositorio.actualizar_camion(db, id_actual, datos)
                return "Camión actualizado."
            repositorio.crear_camion(db, datos)
            return "Camión creado."

        def exito(mensaje: str) -> None:
            self.btn_guardar.configure(state="normal")
            self.lbl_estado.configure(text=mensaje, text_color=VERDE)
            self._limpiar()
            self.cargar()

        def error(exc: Exception) -> None:
            self.btn_guardar.configure(state="normal")
            self.lbl_estado.configure(text=str(exc), text_color=ROJO)

        self.app.ejecutar(trabajo, exito, error)

    def _eliminar(self) -> None:
        if not self._id_actual:
            messagebox.showinfo("Eliminar", "Selecciona un camión de la tabla.")
            return
        db = self.app.db_o_aviso()
        if db is None or not messagebox.askyesno("Eliminar", "¿Eliminar el camión seleccionado?"):
            return
        id_actual = self._id_actual

        def exito(_: Any) -> None:
            self._limpiar()
            self.cargar()

        self.app.ejecutar(lambda: repositorio.eliminar_camion(db, id_actual), exito,
                          lambda exc: self.app.mostrar_error("Eliminar camión", exc))
