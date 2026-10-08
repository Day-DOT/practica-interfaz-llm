# ============================================================
# MOTOR DE REGLAS LÓGICAS
# ============================================================

def evaluar_camion(P, Q, R, S):
    """
    Evalúa un camión utilizando lógica proposicional.

    P = autorización previa
    Q = peso excedido
    R = materiales peligrosos
    S = certificación vigente

    Regresa un diccionario con los resultados.
    """

    # --------------------------------------------------------
    # REGLA 1
    # A = P AND S AND NOT Q
    # --------------------------------------------------------

    acceso_estandar = P and S and not Q

    #representa directamente:

        #A=P∧S∧¬Q

    # --------------------------------------------------------
    # REGLA 2
    # E = P AND (R OR Q)
    # --------------------------------------------------------

    inspeccion_especial = P and (R or Q)
    #representa:

        #E=P∧(R∨Q)    
    # --------------------------------------------------------
    # Generamos la respuesta
    # --------------------------------------------------------

    resultado = {
        "autorizacion": P,
        "peso_excedido": Q,
        "carga_peligrosa": R,
        "certificacion": S,
        "acceso_estandar": acceso_estandar,
        "inspeccion_especial": inspeccion_especial
    }

    return resultado

if __name__ == "__main__":

    resultado = evaluar_camion(
        P=True,
        Q=False,
        R=False,
        S=True
    )

    print("\n========== RESULTADO ==========")

    for clave, valor in resultado.items():
        print(f"{clave}: {valor}")