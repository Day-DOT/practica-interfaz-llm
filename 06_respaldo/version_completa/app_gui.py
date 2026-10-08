"""
app_gui.py
==========
Ventana principal (CustomTkinter) de la aplicación de Control de Acceso y Logística con IA.

Arquitectura por capas::

    gui/*.py                presentación (una pestaña por módulo)
    motor_reglas.py         lógica proposicional (reglas base, V y H, tablas de verdad)
    clasificador_hibrido.py reglas + LLM (Ollama) con validación Pydantic y respaldo
    asistente_rag.py        asistente explicativo con recuperación en MongoDB
    riesgos_eticos.py       matriz de riesgos éticos (inherente y residual)
    reportes.py             exportación CSV / JSON / PDF
    repositorio.py          acceso a datos (CRUD y agregaciones)
    conexion.py, config.py  infraestructura (MongoDB, configuración persistente)

Las operaciones lentas (MongoDB, Ollama) se ejecutan en hilos secundarios y devuelven su
resultado al hilo de la interfaz mediante una cola, de modo que la ventana nunca se congela.

Ejecución::

    python app_gui.py
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter.messagebox as messagebox
from typing import Any, Callable, Optional

import customtkinter as ctk
from pymongo.database import Database

from conexion import cerrar_conexion, obtener_db
from gui.acceso import AccesoTab
from gui.asistente import AsistenteTab
from gui.camiones import CamionesTab
from gui.comun import NARANJA, ROJO, VERDE, PestanaBase, aplicar_estilo_treeview
from gui.configuracion import ConfiguracionTab
from gui.incidentes import IncidentesTab
from gui.panel import PanelTab
from gui.reportes_tab import ReportesTab
from gui.riesgos import RiesgosTab
from gui.simulador import SimuladorTab

logger = logging.getLogger(__name__)

TITULO_APP = "Control de Acceso y Logística con IA"

#: (nombre de la pestaña, clase) en el orden en que se muestran.
PESTANAS: tuple[tuple[str, type[PestanaBase]], ...] = (
    ("Panel", PanelTab),
    ("Control de acceso", AccesoTab),
    ("Simulador", SimuladorTab),
    ("Camiones", CamionesTab),
    ("Incidentes", IncidentesTab),
    ("Asistente", AsistenteTab),
    ("Riesgos éticos", RiesgosTab),
    ("Reportes", ReportesTab),
    ("Configuración", ConfiguracionTab),
)


class App(ctk.CTk):
    """Ventana principal: barra de estado y pestañas."""

    def __init__(self) -> None:
        super().__init__()
        self.title(TITULO_APP)
        self.geometry("1280x820")
        self.minsize(1100, 720)

        self.db: Optional[Database] = None
        self._cola: "queue.Queue[tuple[Callable[[Any], None], Any]]" = queue.Queue()
        self._cerrando = False

        aplicar_estilo_treeview()
        self._construir_barra_estado()
        self.tabs = ctk.CTkTabview(self, command=self._al_cambiar_pestana)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(8, 4))
        self.vistas: dict[str, PestanaBase] = {}
        for nombre, clase in PESTANAS:
            marco = self.tabs.add(nombre)
            marco.grid_columnconfigure(0, weight=1)
            marco.grid_rowconfigure(0, weight=1)
            vista = clase(marco, self)
            vista.grid(row=0, column=0, sticky="nsew")
            self.vistas[nombre] = vista

        self.protocol("WM_DELETE_WINDOW", self._al_cerrar)
        self.after(100, self._procesar_cola)
        self.conectar_bd()

    # ------------------------------------------------------------------ #
    # Servicios para las pestañas
    # ------------------------------------------------------------------ #
    def ejecutar(
        self,
        trabajo: Callable[[], Any],
        al_exito: Callable[[Any], None],
        al_error: Callable[[Exception], None],
    ) -> None:
        """Ejecuta ``trabajo`` en un hilo y despacha el resultado al hilo de la GUI."""

        def corredor() -> None:
            try:
                resultado = trabajo()
            except Exception as exc:  # se reporta a la GUI, nunca se pierde
                logger.exception("Error en tarea en segundo plano")
                self._cola.put((al_error, exc))
            else:
                self._cola.put((al_exito, resultado))

        threading.Thread(target=corredor, daemon=True).start()

    def encolar(self, funcion: Callable[[Any], None]) -> None:
        """Programa ``funcion`` en el hilo de la GUI (seguro de llamar desde otros hilos)."""
        self._cola.put((funcion, None))

    def mostrar_error(self, titulo: str, exc: Exception) -> None:
        messagebox.showerror(titulo, f"{exc}")

    def db_o_aviso(self) -> Optional[Database]:
        """Devuelve la BD conectada o avisa al usuario si no hay conexión."""
        if self.db is None:
            messagebox.showwarning(
                "Sin conexión", "No hay conexión con MongoDB. Pulsa 'Reconectar' e inténtalo de nuevo.")
        return self.db

    def refrescar_todo(self) -> None:
        for vista in self.vistas.values():
            vista.al_conectar()

    # ------------------------------------------------------------------ #
    # Infraestructura
    # ------------------------------------------------------------------ #
    def _procesar_cola(self) -> None:
        if self._cerrando:
            return
        try:
            while True:
                callback, argumento = self._cola.get_nowait()
                try:
                    callback(argumento)
                except Exception:  # un callback defectuoso no debe matar el bucle
                    logger.exception("Error en callback de la interfaz")
        except queue.Empty:
            pass
        self.after(100, self._procesar_cola)

    def _construir_barra_estado(self) -> None:
        barra = ctk.CTkFrame(self, height=34, corner_radius=0)
        barra.pack(side="bottom", fill="x")
        self.lbl_bd = ctk.CTkLabel(barra, text="MongoDB: conectando...", anchor="w")
        self.lbl_bd.pack(side="left", padx=12, pady=3)
        self.btn_reconectar = ctk.CTkButton(barra, text="Reconectar", width=100, height=26, command=self.conectar_bd)
        self.btn_reconectar.pack(side="right", padx=12, pady=3)

    def conectar_bd(self) -> None:
        """Conecta con MongoDB en segundo plano y actualiza el estado."""
        self.lbl_bd.configure(text="MongoDB: conectando...", text_color=NARANJA)
        self.btn_reconectar.configure(state="disabled")

        def exito(db: Database) -> None:
            self.db = db
            self.lbl_bd.configure(text=f"MongoDB: conectado ({db.name})", text_color=VERDE)
            self.btn_reconectar.configure(state="normal")
            self.refrescar_todo()

        def error(exc: Exception) -> None:
            self.db = None
            self.lbl_bd.configure(text="MongoDB: sin conexión", text_color=ROJO)
            self.btn_reconectar.configure(state="normal")
            messagebox.showerror("Base de datos", f"No se pudo conectar a MongoDB:\n\n{exc}")

        self.ejecutar(lambda: obtener_db(forzar_reconexion=True), exito, error)

    def _al_cambiar_pestana(self) -> None:
        vista = self.vistas.get(self.tabs.get())
        if vista is not None:
            vista.al_mostrar()

    def _al_cerrar(self) -> None:
        self._cerrando = True
        try:
            cerrar_conexion()
        finally:
            self.destroy()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    App().mainloop()


if __name__ == "__main__":
    main()
