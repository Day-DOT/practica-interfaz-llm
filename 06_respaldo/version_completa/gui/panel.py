"""
gui/panel.py
============
Panel de control: indicadores (camiones atendidos, incidentes abiertos, riesgos críticos...)
con filtros por fecha y la agregación de incidentes por categoría y semana.
"""

from __future__ import annotations

from typing import Any

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import config
import repositorio
from gui.comun import (AZUL, GRIS, NARANJA, ROJO, VERDE, FiltroFechas, PestanaBase, TarjetaIndicador)

COLORES_CATEGORIA = {"Seguridad": "#d64545", "Documentación": "#e6a117", "Logística": "#1f6aa5", "Otro": "#7a7a7a"}


class PanelTab(PestanaBase):
    """Pestaña con los indicadores y la gráfica semanal de incidentes."""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        cabecera = ctk.CTkFrame(self, fg_color="transparent")
        cabecera.grid(row=0, column=0, sticky="ew", padx=8, pady=(4, 2))
        ctk.CTkLabel(cabecera, text="Panel de control", font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        self.filtro = FiltroFechas(cabecera, self.actualizar)
        self.filtro.pack(side="right")

        self.lbl_estado = ctk.CTkLabel(self, text="", anchor="w")
        self.lbl_estado.grid(row=1, column=0, sticky="ew", padx=10)

        tarjetas = ctk.CTkFrame(self, fg_color="transparent")
        tarjetas.grid(row=2, column=0, sticky="ew", padx=4, pady=4)
        for c in range(5):
            tarjetas.grid_columnconfigure(c, weight=1, uniform="tarj")
        self.t_camiones = TarjetaIndicador(tarjetas, "Camiones atendidos", AZUL)
        self.t_accesos = TarjetaIndicador(tarjetas, "Accesos autorizados", VERDE)
        self.t_inspecciones = TarjetaIndicador(tarjetas, "Inspecciones requeridas", NARANJA)
        self.t_incidentes = TarjetaIndicador(tarjetas, "Incidentes abiertos", NARANJA)
        self.t_riesgos = TarjetaIndicador(tarjetas, "Riesgos críticos", ROJO)
        for c, t in enumerate((self.t_camiones, self.t_accesos, self.t_inspecciones, self.t_incidentes, self.t_riesgos)):
            t.grid(row=0, column=c, sticky="nsew", padx=4)

        self.marco_grafica = ctk.CTkFrame(self)
        self.marco_grafica.grid(row=3, column=0, sticky="nsew", padx=8, pady=(4, 8))
        self.figura = Figure(figsize=(8, 3.4), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figura, master=self.marco_grafica)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def al_mostrar(self) -> None:
        if self.app.db is not None:
            self.actualizar()

    def al_conectar(self) -> None:
        self.actualizar()

    def actualizar(self) -> None:
        """Recalcula indicadores y gráfica para el rango de fechas elegido."""
        db = self.app.db_o_aviso()
        if db is None:
            return
        try:
            desde, hasta = self.filtro.obtener()
        except ValueError as exc:
            self.lbl_estado.configure(text=str(exc), text_color=ROJO)
            return

        self.lbl_estado.configure(text="Calculando indicadores...", text_color=NARANJA)
        alto = config.get("umbral_riesgo_alto")

        def trabajo() -> dict[str, Any]:
            return {
                "stats": repositorio.estadisticas_panel(db, desde, hasta, alto),
                "semanas": repositorio.incidentes_por_categoria_semana(db, desde, hasta),
            }

        def exito(datos: dict[str, Any]) -> None:
            s = datos["stats"]
            self.t_camiones.establecer(s["camiones_atendidos"], f"{s['accesos_total']} accesos en el periodo")
            self.t_accesos.establecer(s["accesos_autorizados"], f"{s['accesos_denegados']} denegados")
            self.t_inspecciones.establecer(s["inspecciones"], "accesos con inspección (E)")
            self.t_incidentes.establecer(s["incidentes_abiertos"], f"de {s['incidentes_total']} incidentes")
            self.t_riesgos.establecer(
                s["riesgos_criticos"], f"sin mitigar (puntaje ≥ {alto}); residuales: {s['riesgos_criticos_residuales']}")
            self._dibujar(datos["semanas"])
            self.lbl_estado.configure(
                text=f"Actualizado. Llamadas al LLM: {s['llm_llamadas']} (latencia media "
                     f"{s['llm_latencia_media_ms']:.0f} ms).", text_color=GRIS)

        def error(exc: Exception) -> None:
            self.lbl_estado.configure(text=f"Error al calcular el panel: {exc}", text_color=ROJO)

        self.app.ejecutar(trabajo, exito, error)

    def _dibujar(self, filas: list[dict[str, Any]]) -> None:
        """Barras apiladas: incidentes por semana, coloreados por categoría."""
        self.figura.clear()
        ax = self.figura.add_subplot(111)
        if not filas:
            ax.text(0.5, 0.5, "Sin incidentes en el periodo seleccionado.", ha="center", va="center",
                    transform=ax.transAxes)
            ax.axis("off")
        else:
            semanas = sorted({f["semana"] for f in filas})
            categorias = sorted({f["categoria"] for f in filas})
            base = [0] * len(semanas)
            for cat in categorias:
                valores = [next((f["total"] for f in filas if f["semana"] == s and f["categoria"] == cat), 0)
                           for s in semanas]
                ax.bar(semanas, valores, bottom=base, label=cat, color=COLORES_CATEGORIA.get(cat, "#999999"))
                base = [b + v for b, v in zip(base, valores)]
            ax.set_title("Incidentes por categoría y semana", fontsize=11)
            ax.set_ylabel("Incidentes")
            ax.legend(fontsize=8)
            ax.tick_params(axis="x", labelrotation=30, labelsize=8)
            ax.yaxis.get_major_locator().set_params(integer=True)
        self.figura.tight_layout()
        self.canvas.draw_idle()
