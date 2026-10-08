# Informe técnico

## 1. Arquitectura

Arquitectura por capas (ver README): presentación (`gui/`), servicios de dominio
(reglas, clasificador, asistente, riesgos, reportes), acceso a datos (`repositorio.py`)
e infraestructura (`conexion.py`, `config.py`). Las tareas lentas (MongoDB, Ollama) se
ejecutan en hilos y devuelven el resultado a la interfaz mediante una cola.

## 2. Esquema de colecciones

- **camiones**: `placa` (única), `camion_id`, `empresa`, `autorizacion`,
  `certificacion_conductor {conductor, vigencia}`.
- **accesos**: `placa`, `camion_id`, `operador`, `fecha`, `P`, `Q`, `R`, `S`, `A`, `E`,
  `reglas_aplicadas`, `explicacion[]`.
- **incidentes**: `correo`, `clasificacion {categoria, prioridad, origen,
  requiere_revision_humana}`, `datos_extraidos {entidades, resumen}`,
  `estado (nuevo|en_atencion|cerrado)`, `historial[]`.
- **riesgos_eticos**: `modulo`, `nombre`, `descripcion`, `categoria`, `probabilidad`,
  `impacto`, `mitigacion`, `probabilidad_residual`, `impacto_residual`, `historico[]`.
- **evaluaciones_llm**: `tipo`, `prompt`, `respuesta`, `modelo`, `latencia_ms`,
  `coincide_con_reglas`, `valido`, `error`, `fecha`.

## 3. Motor de reglas

Premisas: P = autorización previa, Q = peso excedido, R = materiales peligrosos, S = certificación
vigente (las mismas del `logica.py` original).
Reglas base: `A = P ∧ S ∧ ¬Q`, `E = P ∧ (R ∨ Q)`.
Reglas extendidas (orden base → V → H):

- **V** (certificación vencida por fecha; refuerza a S): `A = False`, `E = True`.
- **H** (R y fuera de horario): `A = False`.

Las tablas de verdad (16 filas base, 8 de V, 8 de H y 64 de la regla extendida) están en
`motor_reglas.py` y en la pestaña Simulador. El análisis de redundancias encontró que V
modifica el resultado base en 22 de 64 combinaciones, H cambia A en 1, y que ninguna
combinación con V o H activas autoriza el ingreso (sin contradicciones).

## 4. Prompts usados

Los prompts del clasificador (`PROMPT_SISTEMA`, `PLANTILLA_PROMPT`, `PLANTILLA_REINTENTO`)
y del asistente RAG (`PROMPT_SISTEMA`, `PLANTILLA_USUARIO`) están en los módulos
`clasificador_hibrido.py` y `asistente_rag.py`. El asistente exige responder solo con el
contexto recuperado, citar `[n]` y devolver exactamente
«No tengo información en los registros.» si no hay datos.

## 5. Experimento de clasificación (35 correos etiquetados a mano)

Modelo `llama3.2` (3B) en CPU. Resultados de la ejecución registrada en
`resultados/experimento_resumen.txt`:

| Método | Exactitud categoría | Exactitud prioridad | Ambas | Latencia media |
|---|---|---|---|---|
| Reglas | 85.7 % | 62.9 % | 57.1 % | 1 ms |
| LLM | 57.1 % | 77.1 % | 42.9 % | 11 377 ms |
| Híbrido | 71.4 % | 65.7 % | 42.9 % | 11 379 ms |

Observaciones (sobre este conjunto pequeño; no son resultados generalizables):

- El LLM es mejor estimando la prioridad; las reglas son mejores en la categoría.
- El híbrido queda entre ambos en categoría, y su prioridad se sesga hacia arriba porque
  prevalece la más alta (decisión de diseño: ante la duda, seguridad).
- El híbrido marcó 20 de 35 correos para revisión humana.
- Las matrices de confusión están en `resultados/matrices_confusion.png`.
- Las etiquetas del conjunto las propuso el equipo de desarrollo; conviene que cada
  integrante las revise antes de citar cifras en la exposición.

## 6. Análisis ético

Los riesgos se gestionan en la pestaña Riesgos éticos con valoración inherente y
residual: alucinaciones del LLM, sesgo por ortografía informal, privacidad de datos del
conductor, dependencia de la automatización, reglas rígidas y prioridad subestimada.
La evidencia del experimento respalda el riesgo de sesgo y de errores de categoría del
LLM, lo que justifica la fusión con reglas y la revisión humana.

## 7. Limitaciones

- El LLM local es lento en equipos sin GPU (decenas de segundos por consulta).
- Los resultados del experimento dependen del tamaño del conjunto y de las etiquetas.
