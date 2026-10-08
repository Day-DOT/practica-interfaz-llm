

from .peas import AgenteLogiSmart
from .logica import evaluar_camion
from .incidentes import (
    clasificar_incidente,
    enviar_correo_soporte
)
from .riesgos import EvaluadorRiesgosIA


def main():

    print("\n")
    print("=" * 60)
    print("             LOGISMART PYTHON SUITE")
    print("=" * 60)

    # ========================================================
    # 1. PEAS
    # ========================================================

    agente = AgenteLogiSmart()

    agente.mostrar_peas()

    # ========================================================
    # 2. MOTOR DE REGLAS
    # ========================================================

    print("\n\n========== MOTOR DE REGLAS ==========")

    resultado = evaluar_camion(
        P=True,
        Q=False,
        R=False,
        S=True
    )

    for clave, valor in resultado.items():
        print(f"{clave}: {valor}")

    # ========================================================
    # 3. INCIDENTE
    # ========================================================

    print("\n\n========== CLASIFICACIÓN DE INCIDENTE ==========")

    incidente = clasificar_incidente(
        tipo="Control de acceso",
        descripcion="Vehículo detectado con peso excedido",
        nivel=8
    )

    print(incidente)

    enviar_correo_soporte(
        destinatario="soporte@logismart.com",
        asunto="Incidente LogiSmart",
        mensaje=incidente
    )

    # ========================================================
    # 4. EVALUACIÓN DE RIESGOS
    # ========================================================

    print("\n\n========== EVALUACIÓN DE RIESGOS ==========")

    evaluador = EvaluadorRiesgosIA()

    evaluador.registrar_riesgo(
        modulo="Cámara de detección",
        riesgo="Sesgo en condiciones nocturnas",
        categoria="Sesgo",
        impacto="Alto",
        probabilidad="Media",
        mitigacion="Realizar pruebas con diferentes condiciones de iluminación"
    )

    evaluador.registrar_riesgo(
        modulo="Sistema de vigilancia",
        riesgo="Uso inadecuado de información personal",
        categoria="Privacidad",
        impacto="Alto",
        probabilidad="Media",
        mitigacion="Aplicar controles de acceso y políticas de retención"
    )

    evaluador.mostrar_riesgos()

    evaluador.exportar_reporte(
        "reportes/reporte_riesgos.json"
    )

    print("\n")
    print("=" * 60)
    print("             SISTEMA FINALIZADO")
    print("=" * 60)


# ============================================================
# PUNTO DE ENTRADA
# ============================================================

if __name__ == "__main__":
    main()