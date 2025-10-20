from typing import Final, Mapping


__all__ = [
    "METRICS_HORIZONS",
    "EFFICACY_CONTRAILS",
    "SURFACE_EARTH",
    "SECONDS_PER_YEAR",
    "DEFAULT_AGWP_AR6_WM2YR_PER_KG",
    "JOOS_AGWP_COEFF_WM2YR_PER_KG",
    "CONVERSION_FACTORS_AGWP_TO_RF", 
    "CONVERSION_FACTORS_ATR_TO_RF",
    "CONVERSION_ATR_PULSE",
]

METRICS_HORIZONS: Final[tuple[int, ...]] = (20, 50, 100)
EFFICACY_CONTRAILS: Final[float] = 0.37
SURFACE_EARTH: Final[float] = 5.101e14  # m²
SECONDS_PER_YEAR: Final[int] = 31_556_952  # s

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



# New generic conversion factors to convert RF to AGWP or ATR (Dahlmann et al., 2025)
CONVERSION_FACTORS_AGWP_TO_RF: Final[dict[int, dict[str, float]]] = {
        20: {"CH4": 10.6138, "O3": 1.0192, "H2O": 0.75, "NOx": 1.00},
        50: {"CH4": 1.40, "O3": 0.95, "H2O": 0.80, "NOx": 1.00},
        100: {"CH4": 1.55, "O3": 1.00, "H2O": 0.85, "NOx": 1.00},
}
CONVERSION_FACTORS_ATR_TO_RF: Final[dict[int, dict[str, float]]] ={
    20: {"CH4": 0.85, "O3": 0.92, "H2O": 0.88, "NOx": 1.00},
    50: {"CH4": 0.90, "O3": 0.95, "H2O": 0.90, "NOx": 1.00},
    100: {"CH4": 0.95, "O3": 1.00, "H2O": 0.92, "NOx": 1.00},
}

# aCCFs Horizon conversion factors (your P20_F20 / P20_F50 / P20_F100) (Dietmüller et al., 2022)
CONVERSION_ATR_PULSE: Final[dict[int, dict[str, float]]] = {
    20: {"CH4": 10.8, "O3": 14.5, "H2O": 14.5},
    50: {"CH4": 42.5, "O3": 34.1, "H2O": 34.1},
    100: {"CH4": 98.2, "O3": 58.3, "H2O": 58.3},
}
