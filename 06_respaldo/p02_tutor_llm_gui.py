"""
p02_tutor_llm.py
================
Ejercicio 1: implementación de un LLM como tutor con interfaz gráfica.

Cumple los tres puntos de la práctica:
    1. Configuración del sistema distinta al ejemplo original: aquí el LLM es un
       **tutor de finanzas personales** (ver ``CONFIGURACION_TUTOR``).
    2. Interfaz gráfica (CustomTkinter) con chat, botones de ejemplo y estado de carga.
    3. Resumen del historial: el botón "Resumir mi historial" muestra estadísticas de la
       sesión y pide al LLM un resumen breve de lo conversado.

Versión con interfaz gráfica del script original ``p02primertutor_llm.py`` (mismo modelo,
mismo historial de mensajes con rol system/user/assistant y mismo manejo de errores).

Ejecución::

    python p02_tutor_llm_gui.py
"""

from __future__ import annotations

import queue
import threading
from collections import Counter
from datetime import datetime
from typing import Any, Callable

import customtkinter as ctk

MODELO = "llama3.2"
TIMEOUT_S = 240

#: Configuración del sistema (el "ejemplo" que se cambia respecto al original: antes era un
#: profesor de Inteligencia Artificial; ahora es un tutor de finanzas personales).
CONFIGURACION_TUTOR: dict[str, Any] = {
    "nombre": "Tutor de finanzas personales",
    "sistema": (
        "Eres un tutor paciente de finanzas personales para estudiantes universitarios. "
        "Explicas conceptos (presupuesto, ahorro, deuda, interés compuesto, inversión básica) "
        "con ejemplos cortos y cifras sencillas. Respondes en español, en máximo 6 líneas, "
        "y terminas con una pregunta breve para comprobar que el estudiante entendió. "
        "No das asesoría de inversión personalizada ni inventas datos de mercado."
    ),
    "ejemplos": ("¿Qué es el interés compuesto?", "¿Cómo armo un presupuesto mensual?",
                 "¿Qué diferencia hay entre ahorrar e invertir?"),
    "temperatura": 0.4,
}
MAX_TURNOS_CONTEXTO = 8


class TutorApp(ctk.CTk):
    """Ventana del tutor: chat + resumen del historial."""

    def __init__(self) -> None:
        super().__init__()
        self.title(CONFIGURACION_TUTOR["nombre"])
        self.geometry("820x640")
        self.historial: list[dict[str, str]] = []
        self.tiempos: list[datetime] = []
        self._cola: "queue.Queue[Callable[[], None]]" = queue.Queue()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        cab = ctk.CTkFrame(self, fg_color="transparent")
        cab.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        ctk.CTkLabel(cab, text=CONFIGURACION_TUTOR["nombre"], font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")
        ctk.CTkButton(cab, text="Resumir mi historial", command=self._resumir).pack(side="right")

        self.chat = ctk.CTkScrollableFrame(self)
        self.chat.grid(row=1, column=0, sticky="nsew", padx=10, pady=8)

        ej = ctk.CTkFrame(self, fg_color="transparent")
        ej.grid(row=2, column=0, sticky="ew", padx=10)
        for texto in CONFIGURACION_TUTOR["ejemplos"]:
            ctk.CTkButton(ej, text=texto, height=26, fg_color="#7a7a7a",
                          command=lambda t=texto: self._preguntar(t)).pack(side="left", padx=3)

        ent = ctk.CTkFrame(self, fg_color="transparent")
        ent.grid(row=3, column=0, sticky="ew", padx=10, pady=10)
        ent.grid_columnconfigure(0, weight=1)
        self.entrada = ctk.CTkEntry(ent, placeholder_text="Escribe tu pregunta sobre finanzas...")
        self.entrada.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.entrada.bind("<Return>", lambda _e: self._preguntar(self.entrada.get()))
        self.btn = ctk.CTkButton(ent, text="Enviar", width=90, command=lambda: self._preguntar(self.entrada.get()))
        self.btn.grid(row=0, column=1)

        self._burbuja("Hola, soy tu tutor de finanzas personales. ¿Qué quieres aprender hoy?", "tutor")
        self.after(100, self._procesar)

    # --- utilidades de interfaz ---
    def _procesar(self) -> None:
        try:
            while True:
                self._cola.get_nowait()()
        except queue.Empty:
            pass
        self.after(100, self._procesar)

    def _burbuja(self, texto: str, autor: str) -> ctk.CTkLabel:
        usuario = autor == "usuario"
        b = ctk.CTkLabel(self.chat, text=texto, wraplength=620, justify="left", anchor="w", corner_radius=10, padx=12,
                         pady=8, fg_color=("#cfe3ff", "#1f4e8c") if usuario else ("#e3e3e3", "#3a3a3a"))
        b.pack(anchor="e" if usuario else "w", padx=8, pady=4)
        self.update_idletasks()
        try:
            self.chat._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass
        return b

    # --- conversación ---
    def _llamar(self, mensajes: list[dict[str, str]]) -> str:
        import ollama
        cliente = ollama.Client(timeout=TIMEOUT_S)
        r = cliente.chat(model=MODELO, messages=mensajes,
                         options={"temperature": CONFIGURACION_TUTOR["temperatura"], "num_ctx": 4096})
        return (r["message"]["content"] or "").strip()

    def _preguntar(self, texto: str) -> None:
        texto = texto.strip()
        if not texto or str(self.btn.cget("state")) == "disabled":
            return
        self.entrada.delete(0, "end")
        self._burbuja(texto, "usuario")
        espera = self._burbuja("Pensando...", "tutor")
        self.btn.configure(state="disabled")
        self.historial.append({"role": "user", "content": texto})
        self.tiempos.append(datetime.now())
        mensajes = [{"role": "system", "content": CONFIGURACION_TUTOR["sistema"]}] + self.historial[-2 * MAX_TURNOS_CONTEXTO:]

        def trabajo() -> None:
            try:
                resp = self._llamar(mensajes) or "(sin respuesta)"
                self.historial.append({"role": "assistant", "content": resp})
            except Exception as exc:  # Ollama apagado, modelo ausente, timeout...
                resp = f"No pude contactar al modelo: {exc}"
                self.historial.pop()  # no deja la pregunta sin respuesta en el historial
                self.tiempos.pop()
            self._cola.put(lambda: (espera.configure(text=resp), self.btn.configure(state="normal")))

        threading.Thread(target=trabajo, daemon=True).start()

    # --- resumen del historial ---
    def _resumir(self) -> None:
        preguntas = [m["content"] for m in self.historial if m["role"] == "user"]
        if not preguntas:
            self._burbuja("Aún no hay historial que resumir. ¡Haz tu primera pregunta!", "tutor")
            return
        palabras = Counter(w.lower().strip("¿?¡!.,") for p in preguntas for w in p.split() if len(w) > 5)
        frecuentes = ", ".join(w for w, _ in palabras.most_common(5)) or "-"
        inicio = self.tiempos[0].strftime("%H:%M")
        self._burbuja(f"Resumen de tu sesión: {len(preguntas)} pregunta(s) desde las {inicio}. "
                      f"Palabras frecuentes: {frecuentes}.", "tutor")
        espera = self._burbuja("Generando resumen de lo aprendido...", "tutor")
        conversacion = "\n".join(f"{'Estudiante' if m['role'] == 'user' else 'Tutor'}: {m['content']}"
                                 for m in self.historial)
        mensajes = [{"role": "system", "content": "Resume en español, en 3 viñetas cortas, lo que aprendió el "
                                                 "estudiante en esta conversación. No agregues información nueva."},
                    {"role": "user", "content": conversacion[-4000:]}]

        def trabajo() -> None:
            try:
                resp = self._llamar(mensajes)
            except Exception as exc:
                resp = f"No pude generar el resumen: {exc}"
            self._cola.put(lambda: espera.configure(text=resp))

        threading.Thread(target=trabajo, daemon=True).start()


if __name__ == "__main__":
    ctk.set_appearance_mode("System")
    TutorApp().mainloop()
