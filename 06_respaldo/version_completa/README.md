# Control de Acceso y Logística con IA

Aplicación modular de escritorio (Python + CustomTkinter) con persistencia en MongoDB,
un LLM local (Ollama, `llama3.2`) y un motor de reglas proposicionales.

## Requisitos

- Python 3.10 o superior
- MongoDB (local, Atlas o el clúster del curso)
- [Ollama](https://ollama.com) con el modelo descargado: `ollama pull llama3.2`

## Instalación

```bash
pip install -r requirements.txt
copy .env.example .env      # y completa MONGO_URI / MONGO_DB
python app_gui.py
```

En la pestaña **Configuración** se pueden cargar los datos de demostración
(o con `python datos_demo.py`).

## Arquitectura por capas

| Capa | Archivos |
|---|---|
| Presentación | `app_gui.py`, `gui/*.py` (una pestaña por módulo) |
| Dominio / servicios | `motor_reglas.py`, `clasificador_hibrido.py`, `asistente_rag.py`, `riesgos_eticos.py`, `reportes.py`, `evaluacion_clasificador.py` |
| Acceso a datos | `repositorio.py` (CRUD y agregaciones) |
| Infraestructura | `conexion.py` (MongoDB), `config.py` (configuración persistente) |
| Datos | `datos/correos_etiquetados.json`, `datos_demo.py`, `resultados/` |

## Premisas del motor de reglas

P = autorización previa, Q = peso excedido, R = materiales peligrosos, S = certificación vigente.
`A = P ∧ S ∧ ¬Q` (ingreso) y `E = P ∧ (R ∨ Q)` (inspección). Reglas extendidas: **V** (certificación
vencida por fecha: A=0, E=1) y **H** (materiales peligrosos fuera de horario: A=0).

## Funcionalidad (pestañas)

1. **Panel**: indicadores con filtro de fechas y gráfica de incidentes por categoría y semana.
2. **Control de acceso**: formulario P/S/Q/R o búsqueda por placa, semáforo y explicación paso a paso.
3. **Simulador**: interruptores en vivo y tablas de verdad (base, regla V, regla H, extendida).
4. **Camiones**: CRUD.
5. **Incidentes**: clasificar un correo, editar el resultado, cambiar estado, historial y baja.
6. **Asistente**: chat RAG que responde solo con datos de MongoDB y cita las fuentes.
7. **Riesgos éticos**: gráfica, riesgo residual (antes/después), alta, edición y baja.
8. **Reportes**: exportar a CSV, JSON y PDF; experimento de clasificación.
9. **Configuración**: modelo de Ollama, umbrales, horario, modo simulación de correo.

## Experimento de clasificación

```bash
python evaluacion_clasificador.py            # reglas + LLM + híbrido
python evaluacion_clasificador.py --sin-llm  # solo reglas
```

Resultados en `resultados/` (JSON, CSV, matrices de confusión PNG y resumen).

## Seguridad

El archivo `.env` contiene credenciales y está excluido por `.gitignore`. No lo subas a Git.

