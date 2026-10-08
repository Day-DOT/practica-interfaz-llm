"""
gui/reportes_tab.py
===================
Reportes: exportar a CSV/JSON/PDF y ejecutar el experimento de clasificación
(reglas vs. LLM vs. híbrido) sobre los correos etiquetados.
"""

from __future__ import annotations

import os
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk

import evaluacion_clasificador as ev
import reportes
from gui.comun import GRIS, NARANJA, ROJO, VERDE, FiltroFechas, PestanaBase, solo_lectura

EXTENSIONES = {"CSV": ".csv", "JSON": ".json", "PDF": ".pdf"}


class ReportesTab(PestanaBase):
    """Exportación de datos y experimento de clasificación."""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        izq = ctk.CTkFrame(self)
        izq.grid(row=0, column=0, sticky="nsew", padx=(4, 6), pady=4)
        ctk.CTkLabel(izq, text="Exportar datos", font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", padx=14, pady=(12, 6))
        ctk.CTkLabel(izq, text="Conjunto de datos").pack(anchor="w", padx=14)
        self.om_tema = ctk.CTkOptionMenu(izq, values=list(reportes.TEMAS.values()), width=260)
        self.om_tema.pack(padx=14, pady=(0, 8))
        ctk.CTkLabel(izq, text="Periodo (accesos, incidentes y evaluaciones)").pack(anchor="w", padx=14)
        self.filtro = FiltroFechas(izq, lambda: None, dias_por_defecto=90)
        self.filtro.pack(padx=14, pady=(0, 8), anchor="w")
        ctk.CTkLabel(izq, text="Formato").pack(anchor="w", padx=14)
        self.sb_formato = ctk.CTkSegmentedButton(izq, values=list(reportes.FORMATOS))
        self.sb_formato.set("CSV")
        self.sb_formato.pack(padx=14, pady=(0, 10), anchor="w")
        self.btn_exportar = ctk.CTkButton(izq, text="Exportar...", command=self._exportar)
        self.btn_exportar.pack(fill="x", padx=14, pady=4)
        self.lbl_exportar = ctk.CTkLabel(izq, text="", wraplength=280, justify="left")
        self.lbl_exportar.pack(anchor="w", padx=14, pady=(4, 12))

        der = ctk.CTkFrame(self)
        der.grid(row=0, column=1, sticky="nsew", padx=(0, 4), pady=4)
        der.grid_columnconfigure(0, weight=1)
        der.grid_rowconfigure(3, weight=1)
        ctk.CTkLabel(der, text="Experimento de clasificación (35 correos etiquetados)",
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(der, justify="left", text_color=GRIS, wraplength=560,
                     text="Compara reglas, LLM e híbrido: exactitud, matriz de confusión y latencia. "
                          "Con el LLM puede tardar varios minutos. Los resultados se guardan en la carpeta "
                          "'resultados'.").grid(row=1, column=0, sticky="w", padx=14)
        barra = ctk.CTkFrame(der, fg_color="transparent")
        barra.grid(row=2, column=0, sticky="ew", padx=14, pady=8)
        self.btn_exp = ctk.CTkButton(barra, text="Ejecutar con LLM", command=lambda: self._experimento(True))
        self.btn_exp.pack(side="left")
        self.btn_exp_reglas = ctk.CTkButton(barra, text="Solo reglas (rápido)", fg_color=GRIS,
                                            command=lambda: self._experimento(False))
        self.btn_exp_reglas.pack(side="left", padx=8)
        self.btn_carpeta = ctk.CTkButton(barra, text="Abrir carpeta de resultados", fg_color=GRIS,
                                         command=self._abrir_carpeta)
        self.btn_carpeta.pack(side="left")
        self.barra_prog = ctk.CTkProgressBar(der)
        self.barra_prog.set(0)
        self.barra_prog.grid(row=2, column=0, sticky="e", padx=14)
        self.barra_prog.grid_remove()
        self.txt_resultado = ctk.CTkTextbox(der, wrap="none", state="disabled", font=ctk.CTkFont(family="Consolas", size=12))
        self.txt_resultado.grid(row=3, column=0, sticky="nsew", padx=14, pady=(0, 6))
        self.lbl_estado = ctk.CTkLabel(der, text="", wraplength=560, justify="left")
        self.lbl_estado.grid(row=4, column=0, sticky="w", padx=14, pady=(0, 10))

    # ------------------------------------------------------------------ #
    def _clave_tema(self) -> str:
        nombre = self.om_tema.get()
        return next(k for k, v in reportes.TEMAS.items() if v == nombre)

    def _exportar(self) -> None:
        db = self.app.db_o_aviso()
        if db is None:
            return
        try:
            desde, hasta = self.filtro.obtener()
        except ValueError as exc:
            messagebox.showwarning("Fechas inválidas", str(exc))
            return
        tema, formato = self._clave_tema(), self.sb_formato.get()
        ruta = filedialog.asksaveasfilename(
            title="Guardar reporte", defaultextension=EXTENSIONES[formato],
            initialfile=f"reporte_{tema}{EXTENSIONES[formato]}",
            filetypes=[(formato, f"*{EXTENSIONES[formato]}")])
        if not ruta:
            return
        self.btn_exportar.configure(state="disabled")
        self.lbl_exportar.configure(text="Generando reporte...", text_color=NARANJA)

        def trabajo() -> tuple[str, int]:
            registros = reportes.obtener_datos(db, tema, desde, hasta)
            return reportes.exportar(registros, ruta, formato, tema), len(registros)

        def exito(res: tuple[str, int]) -> None:
            self.btn_exportar.configure(state="normal")
            self.lbl_exportar.configure(text=f"{res[1]} registros exportados a:\n{res[0]}", text_color=VERDE)

        def error(exc: Exception) -> None:
            self.btn_exportar.configure(state="normal")
            self.lbl_exportar.configure(text=f"Error: {exc}", text_color=ROJO)

        self.app.ejecutar(trabajo, exito, error)

    def _experimento(self, usar_llm: bool) -> None:
        if usar_llm and not messagebox.askyesno(
                "Experimento con LLM", "Se enviarán 35 correos a Ollama; puede tardar varios minutos. ¿Continuar?"):
            return
        db = self.app.db
        self.btn_exp.configure(state="disabled")
        self.btn_exp_reglas.configure(state="disabled")
        self.barra_prog.grid()
        self.barra_prog.set(0)
        self.lbl_estado.configure(text="Ejecutando experimento...", text_color=NARANJA)
        solo_lectura(self.txt_resultado, "")

        def progreso(hechos: int, total: int, mensaje: str) -> None:
            self.app.encolar(lambda _: (self.barra_prog.set(hechos / total),
                                        self.lbl_estado.configure(text=mensaje, text_color=NARANJA)))

        def terminar() -> None:
            self.btn_exp.configure(state="normal")
            self.btn_exp_reglas.configure(state="normal")
            self.barra_prog.grid_remove()

        def exito(resultado: dict[str, Any]) -> None:
            terminar()
            solo_lectura(self.txt_resultado, ev.resumen_texto(resultado))
            self.lbl_estado.configure(text=f"Listo. Archivos guardados en: {ev.CARPETA_RESULTADOS}", text_color=VERDE)

        def error(exc: Exception) -> None:
            terminar()
            self.lbl_estado.configure(text=f"Error en el experimento: {exc}", text_color=ROJO)

        self.app.ejecutar(lambda: ev.ejecutar_experimento(usar_llm=usar_llm, progreso=progreso, db=db), exito, error)

    def _abrir_carpeta(self) -> None:
        ev.CARPETA_RESULTADOS.mkdir(exist_ok=True)
        try:
            os.startfile(ev.CARPETA_RESULTADOS)  # solo Windows
        except (AttributeError, OSError):
            messagebox.showinfo("Resultados", f"Carpeta de resultados:\n{ev.CARPETA_RESULTADOS}")
