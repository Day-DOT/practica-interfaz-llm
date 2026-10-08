"""
gui/riesgos.py
==============
Matriz de riesgos éticos: gráfica (dispersión inherente/residual + puntaje antes/después),
y alta, edición y baja de riesgos con su histórico.
"""

from __future__ import annotations

from typing import Any, Optional

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from tkinter import messagebox

import riesgos_eticos as re_
from gui.comun import GRIS, NARANJA, ROJO, VERDE, PestanaBase, Tabla, solo_lectura

ESCALA = [str(n) for n in range(1, 6)]


class RiesgosTab(PestanaBase):
    """Pestaña de gestión y visualización de riesgos éticos."""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, app)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=3)
        self.grid_rowconfigure(1, weight=2)
        self._id_actual: Optional[str] = None
        self._riesgos: dict[str, dict[str, Any]] = {}
        self._canvas_fig: Optional[FigureCanvasTkAgg] = None

        self._construir_formulario()
        self.marco_grafica = ctk.CTkFrame(self)
        self.marco_grafica.grid(row=0, column=1, sticky="nsew", padx=(0, 4), pady=(2, 4))
        ctk.CTkLabel(self.marco_grafica, text="Cargando riesgos...").place(relx=0.5, rely=0.5, anchor="center")

        inferior = ctk.CTkFrame(self, fg_color="transparent")
        inferior.grid(row=1, column=0, columnspan=2, sticky="nsew")
        inferior.grid_columnconfigure(0, weight=3)
        inferior.grid_columnconfigure(1, weight=1)
        inferior.grid_rowconfigure(0, weight=1)
        self.tabla = Tabla(inferior, [
            ("n", "#", 35), ("modulo", "Módulo", 120), ("nombre", "Riesgo", 230), ("categoria", "Categoría", 90),
            ("antes", "Antes", 55), ("despues", "Después", 65), ("nivel", "Nivel residual", 100),
        ], altura=6, al_seleccionar=self._al_seleccionar)
        self.tabla.grid(row=0, column=0, sticky="nsew", padx=(4, 6))
        histo = ctk.CTkFrame(inferior)
        histo.grid(row=0, column=1, sticky="nsew", padx=(0, 4))
        histo.grid_rowconfigure(1, weight=1)
        histo.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(histo, text="Histórico del riesgo", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w", padx=8, pady=(6, 0))
        self.txt_historico = ctk.CTkTextbox(histo, wrap="word", state="disabled")
        self.txt_historico.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)

    def _construir_formulario(self) -> None:
        form = ctk.CTkScrollableFrame(self, width=300, label_text="Alta / edición de riesgo")
        form.grid(row=0, column=0, sticky="ns", padx=(4, 6), pady=(2, 4))
        self.ent_nombre = self._campo(form, "Nombre del riesgo")
        ctk.CTkLabel(form, text="Módulo").pack(anchor="w", padx=6)
        self.om_modulo = ctk.CTkOptionMenu(form, values=list(re_.MODULOS), width=250)
        self.om_modulo.pack(padx=6, pady=(0, 4))
        ctk.CTkLabel(form, text="Categoría").pack(anchor="w", padx=6)
        self.om_categoria = ctk.CTkOptionMenu(form, values=list(re_.CATEGORIAS), width=250)
        self.om_categoria.pack(padx=6, pady=(0, 4))
        ctk.CTkLabel(form, text="Descripción").pack(anchor="w", padx=6)
        self.txt_desc = ctk.CTkTextbox(form, height=60, width=250, wrap="word")
        self.txt_desc.pack(padx=6, pady=(0, 4))
        ctk.CTkLabel(form, text="Mitigación").pack(anchor="w", padx=6)
        self.txt_mitig = ctk.CTkTextbox(form, height=60, width=250, wrap="word")
        self.txt_mitig.pack(padx=6, pady=(0, 4))

        self.escalas: dict[str, ctk.CTkOptionMenu] = {}
        grid = ctk.CTkFrame(form, fg_color="transparent")
        grid.pack(padx=6, pady=4)
        for fila, (clave, titulo) in enumerate((
            ("probabilidad", "Probabilidad (antes)"), ("impacto", "Impacto (antes)"),
            ("probabilidad_residual", "Probabilidad (después)"), ("impacto_residual", "Impacto (después)"),
        )):
            ctk.CTkLabel(grid, text=titulo).grid(row=fila, column=0, sticky="w", pady=2)
            om = ctk.CTkOptionMenu(grid, values=ESCALA, width=70)
            om.grid(row=fila, column=1, padx=(8, 0), pady=2)
            self.escalas[clave] = om

        self.btn_guardar = ctk.CTkButton(form, text="Agregar riesgo", command=self._guardar)
        self.btn_guardar.pack(fill="x", padx=6, pady=(10, 4))
        ctk.CTkButton(form, text="Nuevo / limpiar", fg_color=GRIS, command=self._limpiar).pack(fill="x", padx=6, pady=2)
        ctk.CTkButton(form, text="Eliminar", fg_color=ROJO, command=self._eliminar).pack(fill="x", padx=6, pady=2)
        self.lbl_estado = ctk.CTkLabel(form, text="", wraplength=250, justify="left")
        self.lbl_estado.pack(anchor="w", padx=6, pady=6)
        self._limpiar()

    @staticmethod
    def _campo(marco: Any, etiqueta: str) -> ctk.CTkEntry:
        ctk.CTkLabel(marco, text=etiqueta).pack(anchor="w", padx=6)
        ent = ctk.CTkEntry(marco, width=250)
        ent.pack(padx=6, pady=(0, 4))
        return ent

    # ------------------------------------------------------------------ #
    def al_mostrar(self) -> None:
        if self.app.db is not None:
            self.cargar()

    def al_conectar(self) -> None:
        self.cargar()

    def cargar(self) -> None:
        db = self.app.db_o_aviso()
        if db is None:
            return

        def exito(riesgos: list[dict[str, Any]]) -> None:
            self._riesgos = {str(r["_id"]): r for r in riesgos}
            filas = []
            for n, r in enumerate(riesgos, start=1):
                antes = int(r["probabilidad"] * r["impacto"])
                despues = int(r.get("probabilidad_residual", r["probabilidad"]) *
                              r.get("impacto_residual", r["impacto"]))
                filas.append((f"R{n}", r.get("modulo", ""), r["nombre"], r.get("categoria", ""),
                              antes, despues, re_.nivel(despues)))
            self.tabla.cargar(filas, list(self._riesgos))
            self._dibujar(riesgos)
            criticos = re_.contar_criticos(riesgos)
            self.lbl_estado.configure(
                text=f"{len(riesgos)} riesgos · críticos antes: {criticos[0]}, después: {criticos[1]}",
                text_color=GRIS)

        def error(exc: Exception) -> None:
            self.lbl_estado.configure(text=f"Error: {exc}", text_color=ROJO)

        self.app.ejecutar(lambda: re_.obtener_riesgos(db), exito, error)

    def _dibujar(self, riesgos: list[dict[str, Any]]) -> None:
        for hijo in self.marco_grafica.winfo_children():
            hijo.destroy()
        self._canvas_fig = None
        try:
            figura = re_.crear_figura_matriz(riesgos)
        except re_.ErrorRiesgosEticos as exc:
            ctk.CTkLabel(self.marco_grafica, text=str(exc)).place(relx=0.5, rely=0.5, anchor="center")
            return
        self._canvas_fig = FigureCanvasTkAgg(figura, master=self.marco_grafica)
        self._canvas_fig.draw()
        self._canvas_fig.get_tk_widget().pack(fill="both", expand=True)

    def _al_seleccionar(self) -> None:
        iid = self.tabla.seleccionado()
        r = self._riesgos.get(iid or "")
        if not r:
            return
        self._id_actual = iid
        self.ent_nombre.delete(0, "end")
        self.ent_nombre.insert(0, r["nombre"])
        self.om_modulo.set(r.get("modulo", "General") if r.get("modulo") in re_.MODULOS else "General")
        self.om_categoria.set(r.get("categoria", re_.CATEGORIAS[0]) if r.get("categoria") in re_.CATEGORIAS
                              else re_.CATEGORIAS[0])
        self.txt_desc.delete("1.0", "end")
        self.txt_desc.insert("1.0", r.get("descripcion", ""))
        self.txt_mitig.delete("1.0", "end")
        self.txt_mitig.insert("1.0", r.get("mitigacion", ""))
        for clave, om in self.escalas.items():
            om.set(str(r.get(clave, r.get(clave.replace("_residual", ""), 1))))
        self.btn_guardar.configure(text="Guardar cambios")
        historico = [
            f"{h['fecha'].strftime('%Y-%m-%d %H:%M')}  antes {h['probabilidad']}×{h['impacto']}="
            f"{h['probabilidad'] * h['impacto']} · después {h['probabilidad_residual']}×{h['impacto_residual']}="
            f"{h['probabilidad_residual'] * h['impacto_residual']}" for h in r.get("historico", [])]
        solo_lectura(self.txt_historico, "\n".join(historico) or "Sin histórico.")

    def _limpiar(self) -> None:
        self._id_actual = None
        self.ent_nombre.delete(0, "end")
        self.txt_desc.delete("1.0", "end")
        self.txt_mitig.delete("1.0", "end")
        self.om_modulo.set(re_.MODULOS[0])
        self.om_categoria.set(re_.CATEGORIAS[0])
        for clave, om in self.escalas.items():
            om.set("3" if "residual" not in clave else "2")
        self.btn_guardar.configure(text="Agregar riesgo")
        if hasattr(self, "tabla"):
            self.tabla.quitar_seleccion()
            solo_lectura(self.txt_historico, "")

    def _leer(self) -> dict[str, Any]:
        """Lee y valida el formulario.

        Raises:
            ValueError: Con mensaje claro si algo es inválido.
        """
        datos = {
            "nombre": self.ent_nombre.get(), "modulo": self.om_modulo.get(), "categoria": self.om_categoria.get(),
            "descripcion": self.txt_desc.get("1.0", "end"), "mitigacion": self.txt_mitig.get("1.0", "end"),
            **{k: om.get() for k, om in self.escalas.items()},
        }
        re_.validar_riesgo(datos)
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
        self.lbl_estado.configure(text="Guardando...", text_color=NARANJA)

        def trabajo() -> str:
            if id_actual:
                re_.actualizar_riesgo(db, id_actual, datos)
                return "Riesgo actualizado (se añadió al histórico)."
            re_.crear_riesgo(db, datos)
            return "Riesgo agregado."

        def exito(mensaje: str) -> None:
            self._limpiar()
            self.cargar()
            self.lbl_estado.configure(text=mensaje, text_color=VERDE)

        self.app.ejecutar(trabajo, exito, lambda exc: self.lbl_estado.configure(text=str(exc), text_color=ROJO))

    def _eliminar(self) -> None:
        if not self._id_actual:
            messagebox.showinfo("Eliminar", "Selecciona un riesgo de la tabla.")
            return
        db = self.app.db_o_aviso()
        if db is None or not messagebox.askyesno("Eliminar", "¿Eliminar el riesgo seleccionado?"):
            return
        id_actual = self._id_actual

        def exito(_: Any) -> None:
            self._limpiar()
            self.cargar()

        self.app.ejecutar(lambda: re_.eliminar_riesgo(db, id_actual), exito,
                          lambda exc: self.app.mostrar_error("Eliminar riesgo", exc))
