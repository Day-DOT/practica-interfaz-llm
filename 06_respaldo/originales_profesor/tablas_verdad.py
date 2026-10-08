# ============================================================
# TABLA DE VERDAD DEL SISTEMA LOGISMART
# ============================================================

from itertools import product


def generar_tabla_verdad():

    print("\n================================================")
    print("              TABLA DE VERDAD")
    print("================================================")

    print(
        "P Q R S | A = P&S&¬Q | E = P&(R|Q)"
    )

    print("-" * 45)

    # product genera todas las combinaciones
    # posibles de True y False.

    for P, Q, R, S in product([False, True], repeat=4):

        # Regla de acceso
        A = P and S and not Q

        # Regla de inspección
        E = P and (R or Q)

        print(
            f"{int(P)} {int(Q)} {int(R)} {int(S)} | "
            f"     {int(A)}       |      {int(E)}"
        )


if __name__ == "__main__":
    generar_tabla_verdad()