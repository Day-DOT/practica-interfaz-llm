"""
gui/asistente.py
================
Chat con el asistente explicativo (RAG): conversación con historial y fuentes consultadas.
"""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from asistente_rag import ErrorAsistenteRAG, RespuestaRAG, consultar_asistente
from gui.comun import GRIS, PestanaBase

EJEMPLOS = (
    "¿Por qué CAM-102 fue enviado a inspección?",
    "¿Qué incidentes de seguridad hay registrados?",
    "¿Cuántos accesos fueron denegados para ABC-123?",
)


class AsistenteTab(PestanaBase):
    """Chat con historial; cada respuesta lista los registros consultados como fuentes."""

    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._historial: list[dict[str, str]] = []

        barra = ctk.CTkFrame(self, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", padx=6, pady=(2, 0))
        ctk.CTkLabel(barra, text="Ejemplos:", text_color=GRIS).pack(side="left")
        for ejemplo in EJEMPLOS:
            ctk.CTkButton(barra, text=ejemplo, height=24, fg_color=GRIS,
                          command=lambda e=ejemplo: self._usar_ejemplo(e)).pack(side="left", padx=4)
        ctk.CTkButton(barra, text="Nueva conversación", width=130, height=24,
                      command=self._reiniciar).pack(side="right")

        self.chat = ctk.CTkScrollableFrame(self)
        self.chat.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)

        entrada = ctk.CTkFrame(self, fg_color="transparent")
        entrada.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 4))
        entrada.grid_columnconfigure(0, weight=1)
        self.ent = ctk.CTkEntry(entrada, placeholder_text="Pregunta sobre accesos, incidentes o camiones...")
        self.ent.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.ent.bind("<Return>", lambda _e: self._enviar())
        self.btn = ctk.CTkButton(entrada, text="Enviar", width=90, command=self._enviar)
        self.btn.grid(row=0, column=1)

        self._bienvenida()

    def _bienvenida(self) -> None:
        self._burbuja("Hola. Respondo solo con los registros de MongoDB (accesos, incidentes y camiones) "
                      "y cito las fuentes. Si no hay datos, te lo diré.", "asistente")

    def _reiniciar(self) -> None:
        for hijo in self.chat.winfo_children():
            hijo.destroy()
        self._historial.clear()
        self._bienvenida()

    def _usar_ejemplo(self, texto: str) -> None:
        self.ent.delete(0, "end")
        self.ent.insert(0, texto)
        self.ent.focus_set()

    def _bajar(self) -> None:
        self.update_idletasks()
        try:
            self.chat._parent_canvas.yview_moveto(1.0)  # atributo interno de CTkScrollableFrame
        except Exception:
            pass

    def _burbuja(self, texto: str, autor: str) -> ctk.CTkLabel:
        usuario = autor == "usuario"
        burbuja = ctk.CTkLabel(
            self.chat, text=texto, wraplength=720, justify="left", anchor="w", corner_radius=10,
            fg_color=("#cfe3ff", "#1f4e8c") if usuario else ("#e3e3e3", "#3a3a3a"), padx=12, pady=8)
        burbuja.pack(anchor="e" if usuario else "w", padx=8, pady=(6, 0))
        self._bajar()
        return burbuja

    def _fuentes(self, fuentes: list[dict[str, Any]]) -> None:
        if not fuentes:
            return
        lineas = ["Fuentes consultadas:"] + [
            f"  [{f['n']}] {f['etiqueta']}" + ("  ← citada en la respuesta" if f["citada"] else "") for f in fuentes]
        ctk.CTkLabel(self.chat, text="\n".join(lineas), justify="left", anchor="w", text_color=GRIS,
                     font=ctk.CTkFont(size=11), wraplength=720).pack(anchor="w", padx=14)
        self._bajar()

    def _enviar(self) -> None:
        pregunta = self.ent.get().strip()
        if not pregunta or str(self.btn.cget("state")) == "disabled":
            return
        db = self.app.db_o_aviso()
        if db is None:
            return
        self.ent.delete(0, "end")
        self._burbuja(pregunta, "usuario")
        pensando = self._burbuja("Consultando registros y generando respuesta (en equipos sin GPU puede tardar 1-2 minutos)...", "asistente")
        self.btn.configure(state="disabled")
        historial = list(self._historial)

        def exito(r: RespuestaRAG) -> None:
            pensando.configure(text=r.respuesta)
            self._fuentes(r.fuentes)
            self._historial += [{"role": "user", "content": pregunta},
                                {"role": "assistant", "content": r.respuesta}]
            self.btn.configure(state="normal")

        def error(exc: Exception) -> None:
            texto = (f"No pude completar la consulta: {exc}" if isinstance(exc, (ErrorAsistenteRAG, ValueError))
                     else f"Error inesperado: {exc}")
            pensando.configure(text=texto)
            self.btn.configure(state="normal")
            self._bajar()

        self.app.ejecutar(lambda: consultar_asistente(pregunta, db, historial), exito, error)
