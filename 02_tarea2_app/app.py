"""Interfaz gráfica básica: control de acceso, incidentes, asistente y riesgos. Ejecutar: python app.py"""
import os
import queue
import threading
from datetime import date, datetime
from tkinter import messagebox

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import ia
import reglas

ctk.set_appearance_mode("light")
ctk.set_default_color_theme(os.path.join(os.path.dirname(__file__), "rosa.json"))   # tema rosa

ventana = ctk.CTk()
ventana.title("Control de Acceso y Logística con IA")
ventana.geometry("900x680")
ventana.configure(fg_color="#FFF0F5")
ctk.CTkLabel(ventana, text="Control de Acceso y Logística con IA", text_color="#D316DA",
             font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(10, 0))
db = None            # se llena al conectar
incidente = None     # (Incidente, requiere_revision) del último correo clasificado
cola = queue.Queue()


def segundo_plano(trabajo, mostrar):
    """Ejecuta `trabajo` en otro hilo (para no congelar la ventana) y luego `mostrar(resultado)`.
    Si el trabajo falla, el error se muestra en la barra de estado y no se llama a `mostrar`."""
    def correr():
        try:
            cola.put((mostrar, trabajo()))
        except Exception as error:
            cola.put((None, error))
    threading.Thread(target=correr, daemon=True).start()


def revisar_cola():
    """La ventana revisa la cola cada 100 ms y muestra los resultados que van llegando."""
    while not cola.empty():
        mostrar, resultado = cola.get()
        if mostrar is None:
            estado.configure(text=f"Error: {resultado}", text_color="#d64545")
        else:
            try:
                mostrar(resultado)
            except Exception as error:
                estado.configure(text=f"Error en la interfaz: {error}", text_color="#d64545")
    ventana.after(100, revisar_cola)


def escribir(caja, texto):
    caja.configure(state="normal")
    caja.delete("1.0", "end")
    caja.insert("1.0", texto)
    caja.configure(state="disabled")


pestanas = ctk.CTkTabview(ventana)
pestanas.pack(fill="both", expand=True, padx=10, pady=10)
for nombre in ("Control de acceso", "Incidentes", "Asistente", "Riesgos"):
    pestanas.add(nombre)
estado = ctk.CTkLabel(ventana, text="Conectando a MongoDB...")
estado.pack(pady=(0, 6))

# ------------------------------------------------------------ control de acceso
t = pestanas.tab("Control de acceso")
placa = ctk.CTkEntry(t, placeholder_text="Placa (ej. ABC-123)", width=200)
placa.grid(row=0, column=0, padx=10, pady=8, sticky="w")
vence = ctk.CTkEntry(t, placeholder_text="Vence certificación AAAA-MM-DD", width=230)
vence.grid(row=0, column=1, padx=10)
hora = ctk.CTkEntry(t, placeholder_text="Hora (0-23)", width=100)
hora.insert(0, str(datetime.now().hour))
hora.grid(row=0, column=2, padx=10)
interruptores = {}
premisas = [("P", "Autorización previa"), ("Q", "Peso excedido"),
            ("R", "Materiales peligrosos"), ("S", "Certificación vigente")]
for fila, (letra, texto) in enumerate(premisas, start=1):
    interruptores[letra] = ctk.CTkSwitch(t, text=f"{letra} - {texto}")
    interruptores[letra].grid(row=fila, column=0, padx=10, pady=4, sticky="w")
resultado = ctk.CTkLabel(t, text="", font=ctk.CTkFont(size=20, weight="bold"))
resultado.grid(row=5, column=0, columnspan=3, pady=8)
explicacion = ctk.CTkTextbox(t, height=190, width=820, state="disabled")
explicacion.grid(row=6, column=0, columnspan=3, padx=10)


def evaluar():
    try:
        vencimiento = date.fromisoformat(vence.get()) if vence.get().strip() else None
        h = int(hora.get())
    except ValueError:
        messagebox.showwarning("Datos inválidos", "La fecha debe ser AAAA-MM-DD y la hora un número de 0 a 23.")
        return
    if not placa.get().strip():
        messagebox.showwarning("Falta la placa", "Escribe la placa del camión.")
        return
    p, q, r, s = (bool(interruptores[x].get()) for x in "PQRS")
    A, E, pasos = reglas.evaluar(p, q, r, s, vencimiento, h)
    resultado.configure(text=f"{'AUTORIZADO' if A else 'DENEGADO'}  |  Inspección: {'SÍ' if E else 'NO'}",
                        text_color="#2e9e5b" if A else "#d64545")
    escribir(explicacion, "\n".join(pasos))
    if db is None:
        estado.configure(text="Evaluado, pero NO guardado: sin conexión a MongoDB", text_color="#d64545")
        return
    registro = {"placa": placa.get().strip().upper(), "fecha": datetime.now(), "operador": "operador1",
                "P": p, "Q": q, "R": r, "S": s, "A": A, "E": E, "explicacion": pasos}
    segundo_plano(lambda: db.accesos.insert_one(registro),
                  lambda _: estado.configure(text="Acceso guardado en la bitácora", text_color="#2e9e5b"))


ctk.CTkButton(t, text="Evaluar y guardar", command=evaluar).grid(row=1, column=1, rowspan=2, padx=10)

# ------------------------------------------------------------------- incidentes
t = pestanas.tab("Incidentes")
correo = ctk.CTkTextbox(t, height=130, width=840)
correo.pack(padx=10, pady=6)
fila = ctk.CTkFrame(t, fg_color="transparent")
fila.pack()
salida = ctk.CTkLabel(t, text="", wraplength=820, justify="left")
salida.pack(pady=6)
lista = ctk.CTkTextbox(t, height=180, width=840, state="disabled")
lista.pack(padx=10)


def clasificar():
    texto = correo.get("1.0", "end").strip()
    if not texto:
        messagebox.showwarning("Correo vacío", "Pega el texto del correo.")
        return
    salida.configure(text="Clasificando con Ollama (puede tardar)...")

    def mostrar(res):
        global incidente
        incidente = res
        datos, revision = res
        salida.configure(text=f"Categoría: {datos.categoria} | Prioridad: {datos.prioridad} | "
                              f"Entidades: {', '.join(datos.entidades) or '-'}\nResumen: {datos.resumen}"
                              + ("\n⚠ Requiere revisión humana (LLM y reglas no coinciden)" if revision else ""))
    segundo_plano(lambda: ia.clasificar(texto), mostrar)


def guardar_incidente():
    if incidente is None or db is None:
        messagebox.showinfo("Incidentes", "Primero clasifica un correo y verifica la conexión.")
        return
    datos, revision = incidente
    doc = {"correo": correo.get("1.0", "end").strip(), "estado": "nuevo", "fecha": datetime.now(),
           "clasificacion": {"categoria": datos.categoria, "prioridad": datos.prioridad,
                             "requiere_revision_humana": revision},
           "datos_extraidos": {"entidades": datos.entidades, "resumen": datos.resumen}}

    def mostrar(_):
        estado.configure(text="Incidente guardado", text_color="#2e9e5b")
        ver_incidentes()
    segundo_plano(lambda: db.incidentes.insert_one(doc), mostrar)


def ver_incidentes():
    if db is None:
        return
    segundo_plano(lambda: list(db.incidentes.find().sort("_id", -1).limit(10)),
                  lambda docs: escribir(lista, "\n".join(
                      f"{d['fecha']:%Y-%m-%d %H:%M} | {d['clasificacion']['categoria']} | "
                      f"{d['clasificacion']['prioridad']} | {d['estado']} | {d['datos_extraidos']['resumen'][:70]}"
                      for d in docs)))


ctk.CTkButton(fila, text="Clasificar", command=clasificar).pack(side="left", padx=6)
ctk.CTkButton(fila, text="Guardar en MongoDB", command=guardar_incidente).pack(side="left", padx=6)
ctk.CTkButton(fila, text="Ver guardados", command=ver_incidentes).pack(side="left", padx=6)

# -------------------------------------------------------------------- asistente
t = pestanas.tab("Asistente")
chat = ctk.CTkTextbox(t, height=400, width=840, state="disabled")
chat.pack(padx=10, pady=6)
pregunta = ctk.CTkEntry(t, width=700, placeholder_text="Ej: ¿Por qué ABC-123 fue enviado a inspección?")
pregunta.pack(side="left", padx=10)


def agregar(texto):
    chat.configure(state="normal")
    chat.insert("end", texto + "\n\n")
    chat.configure(state="disabled")
    chat.see("end")


def enviar():
    texto = pregunta.get().strip()
    if not texto:
        return
    if db is None:
        agregar("Asistente: aún no hay conexión a MongoDB. Revisa la barra de estado de abajo.")
        return
    pregunta.delete(0, "end")
    agregar("Tú: " + texto + "\nAsistente: consultando registros (puede tardar)...")

    def consultar():
        try:
            return ia.preguntar(db, texto)
        except Exception as error:
            return f"Error: {error}\n(¿Está Ollama abierto? Prueba 'ollama list' en una terminal.)"
    segundo_plano(consultar, lambda r: agregar("Asistente: " + r))


pregunta.bind("<Return>", lambda e: enviar())
ctk.CTkButton(t, text="Enviar", width=100, command=enviar).pack(side="left")

# ---------------------------------------------------------------------- riesgos
t = pestanas.tab("Riesgos")
marco = ctk.CTkFrame(t)


def dibujar():
    if db is None:
        return

    def mostrar(docs):
        fig = Figure(figsize=(8, 4.6))
        ax = fig.add_subplot(111)
        for n, d in enumerate(docs, start=1):
            ax.scatter(d["probabilidad"], d["impacto"], c="red", s=150)                  # antes de mitigar
            ax.scatter(d["probabilidad_residual"], d["impacto_residual"], c="green", marker="D", s=100)  # después
            ax.annotate(f"R{n}", (d["probabilidad"], d["impacto"]), xytext=(6, 6), textcoords="offset points")
        ax.set(xlim=(0.5, 5.5), ylim=(0.5, 5.5), xlabel="Probabilidad", ylabel="Impacto",
               title="Matriz de riesgos (rojo = antes, verde = después de mitigar)")
        ax.grid(True)
        for w in marco.winfo_children():
            w.destroy()
        lienzo = FigureCanvasTkAgg(fig, master=marco)
        lienzo.draw()
        lienzo.get_tk_widget().pack(fill="both", expand=True)
        escribir(leyenda, "\n".join(f"R{n}: {d['nombre']} -> {d.get('mitigacion', '')}"
                                    for n, d in enumerate(docs, start=1)))
    segundo_plano(lambda: ia.riesgos(db), mostrar)


ctk.CTkButton(t, text="Mostrar matriz de riesgos", command=dibujar).pack(pady=6)
marco.pack(fill="both", expand=True, padx=10)
leyenda = ctk.CTkTextbox(t, height=90, state="disabled")
leyenda.pack(fill="x", padx=10, pady=6)


# --------------------------------------------------------------------- conexión
def al_conectar(base):
    global db
    db = base
    estado.configure(text=f"Conectado a MongoDB ({db.name})", text_color="#2e9e5b")
    ver_incidentes()


segundo_plano(ia.conectar, al_conectar)
revisar_cola()
ventana.mainloop()
