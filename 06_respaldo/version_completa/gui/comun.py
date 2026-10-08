"""
gui/comun.py
============
Componentes y utilidades compartidos por todas las pestañas: colores, tabla (Treeview),
semáforo, tarjetas de indicador, filtro de fechas y validación de fechas/horas.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, time, timedelta
from tkinter import ttk
from typing import Any, Callable, Optional, Sequence

import customtkinter as ctk

VERDE, ROJO, NARANJA, GRIS, AZUL = "#2e9e5b", "#d64545", "#e6a117", "#7a7a7a", "#1f6aa5"
COLOR_PRIORIDAD = {"Alta": ROJO, "Media": NARANJA, "Baja": VERDE}


def es_oscuro() -> bool:
    return ctk.get_appearance_mode() == "Dark"


def color_fondo() -> str:
    """Color de fondo de los marcos para dibujar canvas con el mismo tono."""
    return "#2b2b2b" if es_oscuro() else "#dbdbdb"


def parsear_fecha(texto: str, campo: str = "La fecha") -> Optional[date]:
    """Convierte ``AAAA-MM-DD`` en ``date`` (vacío -> ``None``).

    Raises:
        ValueError: Con mensaje claro si el formato es inválido.
    """
    texto = texto.strip()
    if not texto:
        return None
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise ValueError(f"{campo} debe tener el formato AAAA-MM-DD (ej. 2026-10-31).") from None


def parsear_hora(texto: str) -> time:
    """Convierte ``HH:MM`` en ``time`` (vacío -> hora actual).

    Raises:
        ValueError: Con mensaje claro si el formato es inválido.
    """
    texto = texto.strip()
    if not texto:
        return datetime.now().time().replace(second=0, microsecond=0)
    try:
        return datetime.strptime(texto, "%H:%M").time()
    except ValueError:
        raise ValueError("La hora debe tener el formato HH:MM (24 horas, ej. 14:30).") from None


def aplicar_estilo_treeview() -> None:
    """Estilo de ``ttk.Treeview`` acorde al modo claro/oscuro de CustomTkinter."""
    estilo = ttk.Style()
    estilo.theme_use("clam")
    oscuro = es_oscuro()
    fondo, texto = ("#2b2b2b", "#e6e6e6") if oscuro else ("#ffffff", "#1a1a1a")
    cabecera = "#1f538d" if oscuro else "#3a7ebf"
    estilo.configure("Treeview", background=fondo, fieldbackground=fondo, foreground=texto,
                     rowheight=24, borderwidth=0, font=("Segoe UI", 10))
    estilo.configure("Treeview.Heading", background=cabecera, foreground="white", relief="flat",
                     font=("Segoe UI", 10, "bold"))
    estilo.map("Treeview", background=[("selected", "#1f6aa5")], foreground=[("selected", "white")])
    estilo.map("Treeview.Heading", background=[("active", cabecera)])


class Tabla(ctk.CTkFrame):
    """Tabla con barra de desplazamiento sobre ``ttk.Treeview``.

    Args:
        columnas: Lista de ``(clave, encabezado, ancho)``.
        al_seleccionar: Callback sin argumentos que se invoca al cambiar la selección.
    """

    def __init__(self, master: Any, columnas: Sequence[tuple[str, str, int]], altura: int = 8,
                 al_seleccionar: Optional[Callable[[], None]] = None) -> None:
        super().__init__(master, fg_color="transparent")
        self._al_seleccionar = al_seleccionar
        self.arbol = ttk.Treeview(self, show="headings", height=altura, selectmode="browse")
        barra = ttk.Scrollbar(self, orient="vertical", command=self.arbol.yview)
        self.arbol.configure(yscrollcommand=barra.set)
        self.arbol.grid(row=0, column=0, sticky="nsew")
        barra.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.arbol.bind("<<TreeviewSelect>>", lambda _e: self._al_seleccionar and self._al_seleccionar())
        self.reconfigurar(columnas)

    def reconfigurar(self, columnas: Sequence[tuple[str, str, int]]) -> None:
        """Cambia las columnas (vacía la tabla)."""
        self.limpiar()
        self.arbol["columns"] = [c[0] for c in columnas]
        for clave, titulo, ancho in columnas:
            self.arbol.heading(clave, text=titulo)
            self.arbol.column(clave, width=ancho, minwidth=40, anchor="w", stretch=True)

    def limpiar(self) -> None:
        self.arbol.delete(*self.arbol.get_children())

    def cargar(self, filas: Sequence[Sequence[Any]], ids: Optional[Sequence[str]] = None) -> None:
        """Reemplaza el contenido. ``ids`` (opcional) identifica cada fila."""
        self.limpiar()
        for n, fila in enumerate(filas):
            self.arbol.insert("", "end", iid=str(ids[n]) if ids else None, values=list(fila))

    def seleccionado(self) -> Optional[str]:
        """Id (iid) de la fila seleccionada o ``None``."""
        seleccion = self.arbol.selection()
        return seleccion[0] if seleccion else None

    def seleccionar(self, iid: str) -> None:
        if self.arbol.exists(iid):
            self.arbol.selection_set(iid)
            self.arbol.see(iid)

    def quitar_seleccion(self) -> None:
        self.arbol.selection_remove(*self.arbol.selection())


class Semaforo(tk.Canvas):
    """Semáforo de tres luces. ``establecer("verde"|"amarillo"|"rojo"|None)``."""

    def __init__(self, master: Any, tamano: int = 150) -> None:
        super().__init__(master, width=tamano * 0.5, height=tamano, highlightthickness=0, bg=color_fondo())
        self._luces: dict[str, int] = {}
        ancho, alto = tamano * 0.5, tamano
        self.create_rectangle(2, 2, ancho - 2, alto - 2, fill="#222222", outline="#555555", width=2)
        radio = ancho * 0.32
        for n, nombre in enumerate(("rojo", "amarillo", "verde")):
            cy = alto * (0.19 + 0.31 * n)
            self._luces[nombre] = self.create_oval(ancho / 2 - radio, cy - radio, ancho / 2 + radio,
                                                   cy + radio, fill="#3a3a3a", outline="#111111")
        self.establecer(None)

    def establecer(self, activa: Optional[str]) -> None:
        colores = {"rojo": ROJO, "amarillo": "#f2c200", "verde": "#35c26a"}
        for nombre, item in self._luces.items():
            self.itemconfigure(item, fill=colores[nombre] if nombre == activa else "#3a3a3a")


class TarjetaIndicador(ctk.CTkFrame):
    """Tarjeta con un valor grande, un título y un detalle."""

    def __init__(self, master: Any, titulo: str, color: str = AZUL) -> None:
        super().__init__(master, corner_radius=10)
        ctk.CTkLabel(self, text=titulo, font=ctk.CTkFont(size=13), text_color=GRIS).pack(
            anchor="w", padx=14, pady=(10, 0))
        self.valor = ctk.CTkLabel(self, text="-", font=ctk.CTkFont(size=34, weight="bold"), text_color=color)
        self.valor.pack(anchor="w", padx=14)
        self.detalle = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12), text_color=GRIS,
                                    wraplength=190, justify="left")
        self.detalle.pack(anchor="w", padx=14, pady=(0, 10))

    def establecer(self, valor: Any, detalle: str = "") -> None:
        self.valor.configure(text=str(valor))
        self.detalle.configure(text=detalle)


class FiltroFechas(ctk.CTkFrame):
    """Par de campos Desde/Hasta con botón de aplicar y atajos."""

    def __init__(self, master: Any, al_aplicar: Callable[[], None], dias_por_defecto: int = 30) -> None:
        super().__init__(master, fg_color="transparent")
        hoy = date.today()
        ctk.CTkLabel(self, text="Desde").pack(side="left", padx=(0, 4))
        self.ent_desde = ctk.CTkEntry(self, width=105, placeholder_text="AAAA-MM-DD")
        self.ent_desde.insert(0, (hoy - timedelta(days=dias_por_defecto)).isoformat())
        self.ent_desde.pack(side="left")
        ctk.CTkLabel(self, text="Hasta").pack(side="left", padx=(10, 4))
        self.ent_hasta = ctk.CTkEntry(self, width=105, placeholder_text="AAAA-MM-DD")
        self.ent_hasta.insert(0, hoy.isoformat())
        self.ent_hasta.pack(side="left")
        ctk.CTkButton(self, text="Aplicar", width=70, command=al_aplicar).pack(side="left", padx=(10, 0))
        for etiqueta, dias in (("7 d", 7), ("30 d", 30), ("90 d", 90)):
            ctk.CTkButton(self, text=etiqueta, width=42, fg_color=GRIS,
                          command=lambda d=dias: self._atajo(d, al_aplicar)).pack(side="left", padx=(6, 0))

    def _atajo(self, dias: int, al_aplicar: Callable[[], None]) -> None:
        hoy = date.today()
        for ent, valor in ((self.ent_desde, hoy - timedelta(days=dias)), (self.ent_hasta, hoy)):
            ent.delete(0, "end")
            ent.insert(0, valor.isoformat())
        al_aplicar()

    def obtener(self) -> tuple[Optional[date], Optional[date]]:
        """Devuelve ``(desde, hasta)``.

        Raises:
            ValueError: Si una fecha es inválida o ``desde`` es posterior a ``hasta``.
        """
        desde = parsear_fecha(self.ent_desde.get(), "La fecha 'Desde'")
        hasta = parsear_fecha(self.ent_hasta.get(), "La fecha 'Hasta'")
        if desde and hasta and desde > hasta:
            raise ValueError("La fecha 'Desde' no puede ser posterior a 'Hasta'.")
        return desde, hasta


def solo_lectura(caja: ctk.CTkTextbox, texto: str) -> None:
    """Reemplaza el contenido de un ``CTkTextbox`` dejándolo de solo lectura."""
    caja.configure(state="normal")
    caja.delete("1.0", "end")
    caja.insert("1.0", texto)
    caja.configure(state="disabled")


class PestanaBase(ctk.CTkFrame):
    """Base de las pestañas: guarda la referencia a la aplicación y define ``al_mostrar``.

    ``app`` debe ofrecer: ``db``, ``db_o_aviso()``, ``ejecutar(trabajo, ok, error)``,
    y ``mostrar_error(titulo, exc)``.
    """

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app

    def al_mostrar(self) -> None:
        """Se invoca cada vez que la pestaña se hace visible (refrescar datos)."""

    def al_conectar(self) -> None:
        """Se invoca cuando se establece la conexión a la base de datos."""
