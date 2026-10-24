"""Magnitudes derivadas de temperatura y humedad relativa."""
import math

# Constantes de Magnus-Tetens (sobre agua líquida), válidas de -45 a 60 °C.
MAGNUS_A = 17.62
MAGNUS_B = 243.12  # °C


def punto_rocio(temperatura: float, humedad: float) -> float | None:
    """Punto de rocío en °C con la aproximación de Magnus-Tetens; None si no es calculable (HR <= 0)."""
    if not 0.0 < humedad <= 100.0:
        return None
    gamma = math.log(humedad / 100.0) + MAGNUS_A * temperatura / (MAGNUS_B + temperatura)
    return MAGNUS_B * gamma / (MAGNUS_A - gamma)
