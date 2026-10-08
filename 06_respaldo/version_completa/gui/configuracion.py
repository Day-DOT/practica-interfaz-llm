"""
gui/configuracion.py
====================
Configuración: modelo de Ollama, umbrales de riesgo, horario de materiales peligrosos,
modo simulación de correo y carga de datos de demostración.
"""

from __future__ import annotations

from tkinter import messagebox
from typing import Any

import customtkinter as ctk

import config
import datos_demo
from gui.comun import GRIS, NARANJA, ROJO, VERDE, PestanaBase


class ConfiguracionTab(PestanaBase):
    """Formulario de configuración persistente (``config.json``)."""

    CAMPOS = (
        ("modelo_ollama", "Modelo de Ollama", "llama3.2"),
        ("host_ollama", "Host de Ollama (vacío = localhost)", "http://localhost:11434"),
        ("timeout_ollama_s", "Tiempo máximo de espera (segundos)", "60"),
        ("reintentos_llm", "Reintentos del LLM ante JSON inválido (0-5)", "1"),
        ("umbral_riesgo_alto", "Umbral de riesgo ALTO / crítico (puntaje)", "15"),
        ("umbral_riesgo_medio", "Umbral de riesgo MEDIO (puntaje)", "8"),
        ("horario_peligrosos_inicio", "Horario materiales peligrosos: inicio (HH:MM)", "06:00"),
        ("horario_peligrosos_fin", "Horario materiales peligrosos: fin (HH:MM)", "18:00"),
        ("operador", "Operador por defecto", "operador1"),
    )

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        izq = ctk.CTkScrollableFrame(self, label_text="Parámetros")
        izq.grid(row=0, column=0, sticky="nsew", padx=(4, 6), pady=4)
        self.entradas: dict[str, ctk.CTkEntry] = {}
        for clave, etiqueta, ejemplo in self.CAMPOS:
            ctk.CTkLabel(izq, text=etiqueta).pack(anchor="w", padx=8)
            ent = ctk.CTkEntry(izq, width=330, placeholder_text=ejemplo)
            ent.pack(padx=8, pady=(0, 6))
            self.entradas[clave] = ent
        self.sw_simulacion = ctk.CTkSwitch(izq, text="Modo simulación de correo (botón de correos de ejemplo)")
        self.sw_simulacion.pack(anchor="w", padx=8, pady=8)

        botones = ctk.CTkFrame(izq, fg_color="transparent")
        botones.pack(fill="x", padx=8, pady=6)
        ctk.CTkButton(botones, text="Guardar", command=self._guardar).pack(side="left")
        ctk.CTkButton(botones, text="Restaurar valores por defecto", fg_color=GRIS,
                      command=self._restaurar).pack(side="left", padx=8)
        self.lbl_estado = ctk.CTkLabel(izq, text="", wraplength=330, justify="left")
        self.lbl_estado.pack(anchor="w", padx=8, pady=4)

        der = ctk.CTkFrame(self)
        der.grid(row=0, column=1, sticky="nsew", padx=(0, 4), pady=4)
        ctk.CTkLabel(der, text="Ollama", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=14, pady=(12, 2))
        ctk.CTkButton(der, text="Probar conexión y listar modelos", command=self._probar_ollama).pack(
            anchor="w", padx=14, pady=4)
        self.lbl_ollama = ctk.CTkLabel(der, text="", wraplength=380, justify="left")
        self.lbl_ollama.pack(anchor="w", padx=14, pady=(0, 14))

        ctk.CTkLabel(der, text="Datos de demostración", font=ctk.CTkFont(size=16, weight="bold")).pack(
            anchor="w", padx=14, pady=(8, 2))
        ctk.CTkLabel(der, text_color=GRIS, wraplength=380, justify="left",
                     text="Crea camiones, accesos, incidentes y riesgos de ejemplo (marcados como demo). "
                          "'Reiniciar' borra solo los datos demo y los regenera.").pack(anchor="w", padx=14)
        fila = ctk.CTkFrame(der, fg_color="transparent")
        fila.pack(anchor="w", padx=14, pady=6)
        ctk.CTkButton(fila, text="Cargar datos demo", command=lambda: self._demo(False)).pack(side="left")
        ctk.CTkButton(fila, text="Reiniciar datos demo", fg_color=GRIS, command=lambda: self._demo(True)).pack(
            side="left", padx=8)
        self.lbl_demo = ctk.CTkLabel(der, text="", wraplength=380, justify="left")
        self.lbl_demo.pack(anchor="w", padx=14)
        self._cargar_valores()

    def _cargar_valores(self) -> None:
        valores = config.todo()
        for clave, ent in self.entradas.items():
            ent.delete(0, "end")
            ent.insert(0, str(valores[clave]))
        (self.sw_simulacion.select if valores["modo_simulacion_correo"] else self.sw_simulacion.deselect)()

    def _guardar(self) -> None:
        cambios: dict[str, Any] = {k: e.get().strip() for k, e in self.entradas.items()}
        cambios["modo_simulacion_correo"] = bool(self.sw_simulacion.get())
        try:
            config.actualizar(**cambios)
        except ValueError as exc:
            self.lbl_estado.configure(text=str(exc), text_color=ROJO)
            messagebox.showwarning("Configuración inválida", str(exc))
            return
        self.lbl_estado.configure(text="Configuración guardada y aplicada.", text_color=VERDE)

    def _restaurar(self) -> None:
        if messagebox.askyesno("Restaurar", "¿Volver a los valores por defecto?"):
            config.restaurar_defectos()
            self._cargar_valores()
            self.lbl_estado.configure(text="Valores por defecto restaurados.", text_color=VERDE)

    def _probar_ollama(self) -> None:
        self.lbl_ollama.configure(text="Conectando con Ollama...", text_color=NARANJA)

        def trabajo() -> list[str]:
            import ollama
            cliente = ollama.Client(host=config.host_ollama(), timeout=10)
            return [m.model for m in cliente.list().models]

        def exito(modelos: list[str]) -> None:
            actual = config.get("modelo_ollama")
            instalado = any(m.split(":")[0] == actual.split(":")[0] for m in modelos)
            texto = "Conexión correcta. Modelos instalados:\n  " + "\n  ".join(modelos or ["(ninguno)"])
            if not instalado:
                texto += f"\n\n⚠ El modelo configurado '{actual}' no está instalado (ollama pull {actual})."
            self.lbl_ollama.configure(text=texto, text_color=VERDE if instalado else NARANJA)

        self.app.ejecutar(trabajo, exito, lambda exc: self.lbl_ollama.configure(
            text=f"No se pudo conectar con Ollama: {exc}", text_color=ROJO))

    def _demo(self, reiniciar: bool) -> None:
        db = self.app.db_o_aviso()
        if db is None:
            return
        if reiniciar and not messagebox.askyesno("Reiniciar demo", "Se borrarán los datos marcados como demo y se "
                                                                   "volverán a crear. ¿Continuar?"):
            return
        self.lbl_demo.configure(text="Cargando datos de demostración...", text_color=NARANJA)

        def exito(cantidades: dict[str, int]) -> None:
            texto = ("Ya existían datos de demostración (usa 'Reiniciar' para regenerarlos)." if not cantidades
                     else "Datos creados: " + ", ".join(f"{v} {k}" for k, v in cantidades.items()))
            self.lbl_demo.configure(text=texto, text_color=VERDE)
            self.app.refrescar_todo()

        self.app.ejecutar(lambda: datos_demo.sembrar(db, reiniciar), exito,
                          lambda exc: self.lbl_demo.configure(text=f"Error: {exc}", text_color=ROJO))
