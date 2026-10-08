"""Tarea 1: tutor con LLM e interfaz gráfica (versión con ventana de p02primertutor_llm.py).
Cambio de configuración: el tutor ahora es de FINANZAS PERSONALES (el original era de Inteligencia Artificial).
Incluye el botón "Resumir historial". Ejecutar: python tutor_gui.py"""
import os
import queue
import threading
from datetime import datetime

import customtkinter as ctk
import ollama

MODELO = "llama3.2"
SISTEMA = """Eres un tutor de finanzas personales para estudiantes universitarios.
Explica con ejemplos sencillos y cifras fáciles, en máximo 6 líneas, en español.
Al final haz una pregunta corta para comprobar que el estudiante entendió.
No des asesoría de inversión personalizada."""

mensajes = [{"role": "system", "content": SISTEMA}]     # historial de la conversación
preguntas = []                                          # (hora, texto) para el resumen
cola = queue.Queue()

ctk.set_appearance_mode("light")
ctk.set_default_color_theme(os.path.join(os.path.dirname(__file__), "rosa.json"))
ventana = ctk.CTk()
ventana.title("Tutor de finanzas personales")
ventana.geometry("760x600")
ventana.configure(fg_color="#FFF0F5")
ctk.CTkLabel(ventana, text="Tutor de finanzas personales", text_color="#D81B72",
             font=ctk.CTkFont(size=22, weight="bold")).pack(pady=10)
chat = ctk.CTkTextbox(ventana, width=720, height=410, state="disabled", wrap="word")
chat.pack(padx=10)


def escribir(texto):
    chat.configure(state="normal")
    chat.insert("end", texto + "\n\n")
    chat.configure(state="disabled")
    chat.see("end")


def llamar(ok, historial):
    """Pide la respuesta al LLM en otro hilo y deja el resultado en la cola."""
    def correr():
        try:
            cola.put((ok, ollama.chat(model=MODELO, messages=historial)["message"]["content"]))
        except Exception as error:
            cola.put((None, f"No pude contactar al modelo: {error}. ¿Está Ollama abierto?"))
    threading.Thread(target=correr, daemon=True).start()


def revisar_cola():
    while not cola.empty():
        ok, texto = cola.get()
        if ok is None:
            if mensajes[-1]["role"] == "user":
                mensajes.pop()                      # la pregunta no se pudo procesar
                preguntas.pop()
            escribir(texto)
        else:
            ok(texto)
    ventana.after(100, revisar_cola)


def enviar():
    texto = entrada.get().strip()
    if not texto:
        return
    entrada.delete(0, "end")
    mensajes.append({"role": "user", "content": texto})
    preguntas.append((datetime.now().strftime("%H:%M"), texto))
    escribir("Tú: " + texto + "\nTutor: pensando...")

    def mostrar(respuesta):
        mensajes.append({"role": "assistant", "content": respuesta})
        escribir("Tutor: " + respuesta)
    llamar(mostrar, list(mensajes))


def resumir():
    if not preguntas:
        escribir("Aún no hay historial que resumir.")
        return
    escribir(f"Resumen de la sesión: {len(preguntas)} pregunta(s), la primera a las {preguntas[0][0]}.\n"
             "Generando resumen de lo aprendido...")
    conversacion = "\n".join(f"{m['role']}: {m['content']}" for m in mensajes[1:])
    pedido = [{"role": "user", "content": "Resume en 3 viñetas cortas lo que aprendió el estudiante:\n" + conversacion}]
    llamar(lambda r: escribir("Lo aprendido:\n" + r), pedido)


fila = ctk.CTkFrame(ventana, fg_color="transparent")
fila.pack(pady=10)
entrada = ctk.CTkEntry(fila, width=470, placeholder_text="Escribe tu pregunta sobre finanzas...")
entrada.pack(side="left", padx=5)
entrada.bind("<Return>", lambda e: enviar())
ctk.CTkButton(fila, text="Enviar", width=80, command=enviar).pack(side="left", padx=5)
ctk.CTkButton(fila, text="Resumir historial", width=130, command=resumir).pack(side="left", padx=5)
escribir("Tutor: Hola, soy tu tutor de finanzas personales. ¿Qué quieres aprender hoy?")
revisar_cola()
ventana.mainloop()
