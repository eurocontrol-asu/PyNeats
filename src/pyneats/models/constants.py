""" Physical and Radiative Constants for Climate Impact Calculations"""


from typing import Final, Mapping

__all__ = [
    "METRICS_HORIZONS",
    "SURFACE_EARTH",
    "SECONDS_PER_YEAR",
    "DEFAULT_AGWP_AR6_WM2YR_PER_KG",
    "JOOS_AGWP_COEFF_WM2YR_PER_KG",
    "CONVERSION_FACTORS_AGWP_TO_RF", 
    "CONVERSION_FACTORS_ATR_TO_RF",
    "EFFICACY",
    "SOLAR_CONSTANT",
    "ACCF_SCALE_03",
    "ACCF_SCALE_CH4",
    "ACCF_SCALE_H2O",
]

METRICS_HORIZONS: Final[tuple[int, ...]] = (20, 50, 100)
SURFACE_EARTH: Final[float] = 5.101e14  # m²
SECONDS_PER_YEAR: Final[int] = 31_556_952  # s
SOLAR_CONSTANT: Final[float] = 1360.0  # [W m^-2]

# AR6 Table 7.SM.7 (W·m⁻²·yr·kg⁻¹) -> convert to J·m⁻²·kg⁻¹ by multiplying by seconds/year
DEFAULT_AGWP_AR6_WM2YR_PER_KG: Mapping[int, float] = {
    20: 0.0243e-12,
    50: 0.0529e-12,  
    100: 0.0895e-12,
}

# Joos (2013) C(H) in W·m⁻²·yr·kg⁻¹
JOOS_AGWP_COEFF_WM2YR_PER_KG: Mapping[int, float] = {
    20: 25.2e-15,
    50: 53.5e-15,
    100: 92.5e-15,
}

# New generic conversion factors to convert RF to AGWP or ATR (Dahlmann et al., 2025) for Pulse 2025 scenario
CONVERSION_FACTORS_AGWP_TO_RF: Final[dict[int, dict[str, float]]] = {
        20: {"CH4": 10.6318, "O3": 1.0192, "H2O": 1.0192, "PMO": 10.6318},
        50: {"CH4": 13.0968, "O3": 1.0192, "H2O": 1.0192, "PMO": 13.0968},
        100: {"CH4": 13.3563, "O3": 1.0192, "H2O": 1.0192, "PMO": 13.356},
}
CONVERSION_FACTORS_ATR_TO_RF: Final[dict[int, dict[str, float]]] ={
    20: {"CH4": 0.2838, "O3": 0.0337, "H2O": 0.032, "PMO": 0.269},
    50: {"CH4": 0.1898, "O3": 0.0154, "H2O": 0.0146, "PMO": 0.18},
    100: {"CH4": 0.1059, "O3": 0.0082, "H2O": 0.0078, "PMO": 0.1004},
}

# Efficacies as specifided in the RSTS document
EFFICACY: Final[dict[str, float]] = {
    "Contrails": 0.37,
    "CH4": 1.04,
    "O3": 1.05,
    "H2O": 1.0,
    "PMO": 1.0,
}

# ACCFs scaling factors 
ACCF_SCALE_03: Final[Mapping[str, float]] = {"V1.0": 1.97, "V1.0A": 11.0}
ACCF_SCALE_CH4: Final[Mapping[str, float]] = {"V1.0": 2.03, "V1.0A": 35.0}
ACCF_SCALE_H2O: Final[Mapping[str, float]] =  {"V1.0": 1.0, "V1.0A": 1.0}
    
