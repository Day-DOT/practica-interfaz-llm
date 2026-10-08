"""
gui/incidentes.py
=================
Bandeja de incidentes: pegar un correo, clasificarlo (reglas + LLM), editar el resultado,
guardar, cambiar el estado, ver el historial y eliminar.
"""

from __future__ import annotations

import random
from typing import Any, Optional

import customtkinter as ctk
from tkinter import messagebox

import config
import repositorio
from clasificador_hibrido import (CATEGORIAS_VALIDAS, PRIORIDADES_VALIDAS, ResultadoClasificacion,
                                  clasificar_correo_detallado)
from evaluacion_clasificador import cargar_dataset
from gui.comun import (COLOR_PRIORIDAD, GRIS, NARANJA, ROJO, VERDE, PestanaBase, Tabla, solo_lectura)

ORIGENES = {"fusion": "LLM + reglas", "reglas": "Solo reglas (el LLM no respondió)", "llm": "LLM", "manual": "Manual"}


class IncidentesTab(PestanaBase):
    """Bandeja de incidentes con CRUD completo."""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, app)
        self.grid_columnconfigure((0, 1), weight=1, uniform="inc")
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self._id_actual: Optional[str] = None
        self._origen_actual = "manual"
        self._revision_actual = False
        self._incidentes: dict[str, dict[str, Any]] = {}

        self._construir_entrada()
        self._construir_formulario()
        self._construir_lista()

    # ------------------------------------------------------------------ #
    def _construir_entrada(self) -> None:
        marco = ctk.CTkFrame(self, fg_color="transparent")
        marco.grid(row=0, column=0, sticky="ew", padx=(4, 6), pady=(2, 0))
        ctk.CTkLabel(marco, text="1. Pega el correo del incidente", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.btn_simular = ctk.CTkButton(marco, text="Correo simulado", width=120, fg_color=GRIS,
                                         command=self._correo_simulado)
        self.btn_simular.pack(side="right")

        self.txt_correo = ctk.CTkTextbox(self, wrap="word", height=140)
        self.txt_correo.grid(row=1, column=0, sticky="nsew", padx=(4, 6), pady=4)

        barra = ctk.CTkFrame(self, fg_color="transparent")
        barra.grid(row=2, column=0, sticky="ew", padx=(4, 6))
        self.btn_clasificar = ctk.CTkButton(barra, text="Clasificar", command=self._clasificar)
        self.btn_clasificar.pack(side="left")
        ctk.CTkButton(barra, text="Limpiar", width=80, fg_color=GRIS, command=self._limpiar).pack(side="left", padx=8)
        self.progreso = ctk.CTkProgressBar(barra, mode="indeterminate", width=120)
        self.lbl_estado = ctk.CTkLabel(barra, text="", wraplength=330, justify="left")
        self.lbl_estado.pack(side="left", padx=8)

    def _construir_formulario(self) -> None:
        marco = ctk.CTkFrame(self)
        marco.grid(row=0, column=1, rowspan=3, sticky="nsew", padx=(6, 4), pady=2)
        marco.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(marco, text="2. Resultado (editable)", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 4))

        ctk.CTkLabel(marco, text="Categoría").grid(row=1, column=0, sticky="w", padx=12, pady=3)
        self.om_categoria = ctk.CTkOptionMenu(marco, values=list(CATEGORIAS_VALIDAS), width=170)
        self.om_categoria.grid(row=1, column=1, sticky="w", pady=3)
        ctk.CTkLabel(marco, text="Prioridad").grid(row=2, column=0, sticky="w", padx=12, pady=3)
        self.om_prioridad = ctk.CTkOptionMenu(marco, values=list(PRIORIDADES_VALIDAS), width=170,
                                              command=self._color_prioridad)
        self.om_prioridad.grid(row=2, column=1, sticky="w", pady=3)
        ctk.CTkLabel(marco, text="Estado").grid(row=3, column=0, sticky="w", padx=12, pady=3)
        self.om_estado = ctk.CTkOptionMenu(marco, values=list(repositorio.ESTADOS_INCIDENTE), width=170)
        self.om_estado.grid(row=3, column=1, sticky="w", pady=3)
        ctk.CTkLabel(marco, text="Entidades (placas/IDs)").grid(row=4, column=0, sticky="w", padx=12, pady=3)
        self.ent_entidades = ctk.CTkEntry(marco, placeholder_text="ABC-123, CAM-102")
        self.ent_entidades.grid(row=4, column=1, sticky="ew", padx=(0, 12), pady=3)
        ctk.CTkLabel(marco, text="Resumen").grid(row=5, column=0, sticky="nw", padx=12, pady=3)
        self.txt_resumen = ctk.CTkTextbox(marco, height=70, wrap="word")
        self.txt_resumen.grid(row=5, column=1, sticky="ew", padx=(0, 12), pady=3)

        self.lbl_origen = ctk.CTkLabel(marco, text="", wraplength=360, justify="left", corner_radius=6,
                                       text_color="white")
        self.lbl_origen.grid(row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=(6, 4))

        botones = ctk.CTkFrame(marco, fg_color="transparent")
        botones.grid(row=7, column=0, columnspan=2, sticky="ew", padx=12, pady=4)
        self.btn_guardar = ctk.CTkButton(botones, text="Guardar como nuevo", width=140, command=self._guardar)
        self.btn_guardar.pack(side="left", padx=(0, 6))
        self.btn_eliminar = ctk.CTkButton(botones, text="Eliminar", width=80, fg_color=ROJO, command=self._eliminar)
        self.btn_eliminar.pack(side="left")

        ctk.CTkLabel(marco, text="Historial del incidente", font=ctk.CTkFont(weight="bold")).grid(
            row=8, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 0))
        self.txt_historial = ctk.CTkTextbox(marco, height=100, wrap="word", state="disabled")
        self.txt_historial.grid(row=9, column=0, columnspan=2, sticky="nsew", padx=12, pady=(2, 10))
        marco.grid_rowconfigure(9, weight=1)

    def _construir_lista(self) -> None:
        marco = ctk.CTkFrame(self, fg_color="transparent")
        marco.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=4, pady=(6, 2))
        marco.grid_columnconfigure(0, weight=1)
        marco.grid_rowconfigure(1, weight=1)
        barra = ctk.CTkFrame(marco, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(barra, text="Incidentes guardados", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.om_filtro = ctk.CTkOptionMenu(barra, values=["todos", *repositorio.ESTADOS_INCIDENTE], width=120,
                                           command=lambda _v: self.cargar())
        self.om_filtro.pack(side="left", padx=10)
        ctk.CTkButton(barra, text="Actualizar", width=90, command=self.cargar).pack(side="left")
        ctk.CTkButton(barra, text="Nuevo", width=70, fg_color=GRIS, command=self._limpiar).pack(side="left", padx=6)
        self.tabla = Tabla(marco, [
            ("fecha", "Fecha", 120), ("categoria", "Categoría", 100), ("prioridad", "Prioridad", 80),
            ("estado", "Estado", 90), ("revision", "Revisión", 70), ("resumen", "Resumen", 520),
        ], altura=6, al_seleccionar=self._al_seleccionar)
        self.tabla.grid(row=1, column=0, sticky="nsew", pady=(4, 0))

    # ------------------------------------------------------------------ #
    def al_mostrar(self) -> None:
        self.btn_simular.configure(state="normal" if config.get("modo_simulacion_correo") else "disabled")
        if self.app.db is not None:
            self.cargar()

    def al_conectar(self) -> None:
        self.cargar()

    def _color_prioridad(self, valor: str) -> None:
        self.om_prioridad.configure(fg_color=COLOR_PRIORIDAD.get(valor))

    def _cargando(self, activo: bool, mensaje: str = "", color: str = NARANJA) -> None:
        if activo:
            self.progreso.pack(side="left", padx=6, before=self.lbl_estado)
            self.progreso.start()
        else:
            self.progreso.stop()
            self.progreso.pack_forget()
        self.lbl_estado.configure(text=mensaje, text_color=color)

    def _correo_simulado(self) -> None:
        """Modo simulación: rellena la caja con un correo de ejemplo del conjunto etiquetado."""
        try:
            texto = random.choice(cargar_dataset())["texto"]
        except (OSError, ValueError) as exc:
            self.app.mostrar_error("Correo simulado", exc)
            return
        self.txt_correo.delete("1.0", "end")
        self.txt_correo.insert("1.0", texto)

    def _limpiar(self) -> None:
        self._id_actual = None
        self._origen_actual = "manual"
        self._revision_actual = False
        self.txt_correo.delete("1.0", "end")
        self.ent_entidades.delete(0, "end")
        self.txt_resumen.delete("1.0", "end")
        self.om_categoria.set(CATEGORIAS_VALIDAS[-1])
        self.om_prioridad.set(PRIORIDADES_VALIDAS[-1])
        self._color_prioridad(PRIORIDADES_VALIDAS[-1])
        self.om_estado.set("nuevo")
        self.lbl_origen.configure(text="", fg_color="transparent")
        self.btn_guardar.configure(text="Guardar como nuevo")
        solo_lectura(self.txt_historial, "")
        self.tabla.quitar_seleccion()
        self._cargando(False)

    # ------------------------------------------------------------------ #
    # Clasificar
    # ------------------------------------------------------------------ #
    def _clasificar(self) -> None:
        correo = self.txt_correo.get("1.0", "end").strip()
        if not correo:
            messagebox.showwarning("Correo vacío", "Pega el texto del correo antes de clasificar.")
            return
        db = self.app.db
        self.btn_clasificar.configure(state="disabled")
        self._cargando(True, f"Clasificando con {config.get('modelo_ollama')} (puede tardar unos segundos)...")

        def trabajo() -> ResultadoClasificacion:
            resultado = clasificar_correo_detallado(correo)
            if db is not None and resultado.intentos:  # evidencia en evaluaciones_llm
                try:
                    repositorio.registrar_clasificacion(db, resultado)
                except repositorio.ErrorRepositorio:
                    pass
            return resultado

        def exito(res: ResultadoClasificacion) -> None:
            self.btn_clasificar.configure(state="normal")
            self._id_actual = None
            self.btn_guardar.configure(text="Guardar como nuevo")
            self._mostrar(res)
            latencia = sum(i.latencia_ms for i in res.intentos)
            nota = f"Clasificación lista ({latencia / 1000:.1f} s de LLM, {len(res.intentos)} intento(s))."
            if res.llm is None and res.intentos:
                nota = f"El LLM falló ({res.intentos[-1].error[:90]}); se usaron las reglas."
            self._cargando(False, nota, VERDE if res.llm else NARANJA)

        def error(exc: Exception) -> None:
            self.btn_clasificar.configure(state="normal")
            self._cargando(False, f"Error al clasificar: {exc}", ROJO)

        self.app.ejecutar(trabajo, exito, error)

    def _mostrar(self, res: ResultadoClasificacion) -> None:
        f = res.final
        self.om_categoria.set(f.categoria)
        self.om_prioridad.set(f.prioridad)
        self._color_prioridad(f.prioridad)
        self.om_estado.set("nuevo")
        self.ent_entidades.delete(0, "end")
        self.ent_entidades.insert(0, ", ".join(f.entidades))
        self.txt_resumen.delete("1.0", "end")
        self.txt_resumen.insert("1.0", f.resumen)
        self._origen_actual = f.origen
        self._revision_actual = f.requiere_revision_humana
        detalle = f"Origen: {ORIGENES.get(f.origen, f.origen)}."
        if res.llm is not None:
            detalle += f"\nReglas: {res.reglas.categoria}/{res.reglas.prioridad} · LLM: {res.llm.categoria}/{res.llm.prioridad}"
        if f.requiere_revision_humana:
            detalle += "\n⚠ Requiere revisión humana (discrepancia o sin señales claras)."
        self.lbl_origen.configure(text=detalle, fg_color=NARANJA if f.requiere_revision_humana else VERDE)

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #
    def _leer_formulario(self) -> tuple[dict[str, Any], dict[str, Any], str]:
        """Lee y valida el formulario. Retorna ``(clasificacion, datos_extraidos, estado)``.

        Raises:
            ValueError: Con mensaje claro si el resumen está vacío.
        """
        resumen = self.txt_resumen.get("1.0", "end").strip()
        if not resumen:
            raise ValueError("El resumen no puede estar vacío.")
        entidades = [e.strip().upper() for e in self.ent_entidades.get().split(",") if e.strip()]
        clasificacion = {
            "categoria": self.om_categoria.get(), "prioridad": self.om_prioridad.get(),
            "origen": self._origen_actual,
            "requiere_revision_humana": self._revision_actual,
        }
        return clasificacion, {"entidades": entidades, "resumen": resumen}, self.om_estado.get()

    def _guardar(self) -> None:
        db = self.app.db_o_aviso()
        if db is None:
            return
        correo = self.txt_correo.get("1.0", "end").strip()
        try:
            clasificacion, extraidos, estado = self._leer_formulario()
            if not correo:
                raise ValueError("El correo original no puede estar vacío.")
        except ValueError as exc:
            messagebox.showwarning("Datos incompletos", str(exc))
            return
        id_actual = self._id_actual
        if id_actual:  # al editar se conserva la marca de revisión original
            clasificacion["requiere_revision_humana"] = self._incidentes[id_actual]["clasificacion"].get(
                "requiere_revision_humana", False)
        self.btn_guardar.configure(state="disabled")
        self._cargando(True, "Guardando...")

        def trabajo() -> str:
            if id_actual:
                repositorio.actualizar_incidente(db, id_actual, clasificacion=clasificacion,
                                                 datos_extraidos=extraidos, estado=estado)
                return "Incidente actualizado."
            repositorio.crear_incidente(db, correo=correo, clasificacion=clasificacion,
                                        datos_extraidos=extraidos, estado=estado)
            return "Incidente guardado."

        def exito(mensaje: str) -> None:
            self.btn_guardar.configure(state="normal")
            self._cargando(False, mensaje, VERDE)
            self.cargar()

        def error(exc: Exception) -> None:
            self.btn_guardar.configure(state="normal")
            self._cargando(False, f"Error al guardar: {exc}", ROJO)

        self.app.ejecutar(trabajo, exito, error)

    def _eliminar(self) -> None:
        if not self._id_actual:
            messagebox.showinfo("Eliminar", "Selecciona un incidente guardado de la tabla.")
            return
        db = self.app.db_o_aviso()
        if db is None or not messagebox.askyesno("Eliminar", "¿Eliminar el incidente seleccionado?"):
            return
        id_actual = self._id_actual

        def exito(_: Any) -> None:
            self._limpiar()
            self._cargando(False, "Incidente eliminado.", VERDE)
            self.cargar()

        self.app.ejecutar(lambda: repositorio.eliminar_incidente(db, id_actual), exito,
                          lambda exc: self.app.mostrar_error("Eliminar incidente", exc))

    def cargar(self) -> None:
        db = self.app.db
        if db is None:
            return
        filtro = self.om_filtro.get()
        estado = "" if filtro == "todos" else filtro

        def exito(incidentes: list[dict[str, Any]]) -> None:
            self._incidentes = {str(i["_id"]): i for i in incidentes}
            filas = []
            for i in incidentes:
                c, d = i.get("clasificacion", {}), i.get("datos_extraidos", {})
                filas.append((i["fecha"].strftime("%Y-%m-%d %H:%M"), c.get("categoria", ""),
                              c.get("prioridad", ""), i.get("estado", ""),
                              "Sí" if c.get("requiere_revision_humana") else "", d.get("resumen", "")))
            self.tabla.cargar(filas, list(self._incidentes))

        self.app.ejecutar(lambda: repositorio.listar_incidentes(db, estado), exito,
                          lambda exc: self._cargando(False, f"Error al leer incidentes: {exc}", ROJO))

    def _al_seleccionar(self) -> None:
        iid = self.tabla.seleccionado()
        inc = self._incidentes.get(iid or "")
        if not inc:
            return
        self._id_actual = iid
        c, d = inc.get("clasificacion", {}), inc.get("datos_extraidos", {})
        self.txt_correo.delete("1.0", "end")
        self.txt_correo.insert("1.0", inc.get("correo", ""))
        self.om_categoria.set(c.get("categoria", "Otro"))
        self.om_prioridad.set(c.get("prioridad", "Baja"))
        self._color_prioridad(c.get("prioridad", "Baja"))
        self.om_estado.set(inc.get("estado", "nuevo"))
        self.ent_entidades.delete(0, "end")
        self.ent_entidades.insert(0, ", ".join(d.get("entidades", [])))
        self.txt_resumen.delete("1.0", "end")
        self.txt_resumen.insert("1.0", d.get("resumen", ""))
        self._origen_actual = c.get("origen", "manual")
        self.lbl_origen.configure(
            text=f"Origen: {ORIGENES.get(self._origen_actual, self._origen_actual)}"
                 + ("\n⚠ Marcado para revisión humana." if c.get("requiere_revision_humana") else ""),
            fg_color=NARANJA if c.get("requiere_revision_humana") else GRIS)
        self.btn_guardar.configure(text="Guardar cambios")
        eventos = [f"{e['fecha'].strftime('%Y-%m-%d %H:%M')}  {e['evento']}: {e.get('detalle', '')}"
                   for e in inc.get("historial", [])]
        solo_lectura(self.txt_historial, "\n".join(eventos))
