"""Physical and Radiative Constants for Climate Impact Calculations"""

from typing import Final
from collections.abc import Mapping

__all__ = [
    "METRICS_HORIZONS",
    "SURFACE_EARTH",
    "SECONDS_PER_YEAR",
    "CO2_AGWP_COEFF_WM2YR_PER_KG",
    "CONVERSION_FACTORS_AGWP_TO_RF",
    "CONVERSION_FACTORS_ATR_TO_RF",
    "EFFICACY",
    "SOLAR_CONSTANT",
    "ACCF_SCALE_03",
    "ACCF_SCALE_CH4",
    "ACCF_SCALE_H2O",
    "RF_BACKWARD_FACTOR",
]

METRICS_HORIZONS: Final[tuple[int, ...]] = (20, 50, 100)
SURFACE_EARTH: Final[float] = 5.101e14  # m²
SECONDS_PER_YEAR: Final[int] = 31_556_952  # s
SOLAR_CONSTANT: Final[float] = 1360.0  # [W m^-2]

#  CO2 GWP coefficients built with AirClim, alternatives to Joos (2013) (C(H) in W·m⁻²·yr·kg⁻¹)
CO2_AGWP_COEFF_WM2YR_PER_KG: Mapping[int, float] = {
    20: 24.16e-15,
    50: 47.57e-15,
    100: 74.36e-15,
}

# New generic conversion factors to convert RF to AGWP or ATR (Dahlmann et al., 2025) for Pulse 2025 scenario
CONVERSION_FACTORS_AGWP_TO_RF: Final[dict[int, dict[str, float]]] = {
    20: {"CH4": 10.6318, "O3": 1.0192, "H2O": 1.0192, "PMO": 10.6318},
    50: {"CH4": 13.0968, "O3": 1.0192, "H2O": 1.0192, "PMO": 13.0968},
    100: {"CH4": 13.3563, "O3": 1.0192, "H2O": 1.0192, "PMO": 13.356},
}
CONVERSION_FACTORS_ATR_TO_RF: Final[dict[int, dict[str, float]]] = {
    20: {"CH4": 0.2838, "O3": 0.0337, "H2O": 0.032, "PMO": 0.269},
    50: {"CH4": 0.1898, "O3": 0.0154, "H2O": 0.0146, "PMO": 0.18},
    100: {"CH4": 0.1059, "O3": 0.0082, "H2O": 0.0078, "PMO": 0.1004},
}


# Efficacies as specifided in the RSTS document (coming from AirClim)
EFFICACY: Final[dict[str, float]] = {
    "Contrails": 0.37,
    "CH4": 1.04,
    "O3": 1.05,
    "H2O": 1.0,
    "PMO": 1.0,
}

# Historical RF backward calculation factor implicitely used in Dietmuller et al., 2023 and Yin et al., 2023
# not necessary anymore while using modern conversion factors from Dahlmann et al., 2025
# therefore used here to discount accf output value before applying conversion factors from Dahlmann et al., 2025
RF_BACKWARD_FACTOR: Final[dict[str, float]] = {
    "CH4": 0.492,
    "O3": 0.508,
    "H2O": 0.52,
}

# ACCFs scaling factors
ACCF_SCALE_03: Final[Mapping[str, float]] = {"V1.0": 1.97, "V1.0A": 11.0}
ACCF_SCALE_CH4: Final[Mapping[str, float]] = {"V1.0": 2.03, "V1.0A": 35.0}
ACCF_SCALE_H2O: Final[Mapping[str, float]] = {"V1.0": 1.0, "V1.0A": 1.0}
