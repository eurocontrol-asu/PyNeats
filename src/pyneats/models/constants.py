from typing import Final, Mapping


__all__ = [
    "DEFAULT_HORIZONS",
    "DEFAULT_EFFICACY",
    "DEFAULT_SURFACE_EARTH",
    "DEFAULT_SECONDS_PER_YEAR",
    "DEFAULT_AGWP_AR6_WM2YR_PER_KG",
    "HORIZON_CONVERSION_FACTORS"
]

DEFAULT_HORIZONS: Final[tuple[int, ...]] = (20, 50, 100)
DEFAULT_EFFICACY: Final[float] = 0.42
DEFAULT_SURFACE_EARTH: Final[float] = 5.101e14  # m²
DEFAULT_SECONDS_PER_YEAR: Final[int] = 31_556_952  # s

# AR6 Table 7.SM.7 (W·m⁻²·yr·kg⁻¹) -> convert to J·m⁻²·kg⁻¹ by multiplying by seconds/year
DEFAULT_AGWP_AR6_WM2YR_PER_KG: Mapping[int, float] = {
    20: 0.0243e-12,
    50: 0.0529e-12,  
    100: 0.0895e-12,
}

# aCCFs Horizon conversion factors (your P20_F20 / P20_F50 / P20_F100) (Dietmüller et al., 2022)
HORIZON_CONVERSION_FACTORS: Final[dict[int, dict[str, float]]] = {
    20: {"CH4": 10.8, "O3": 14.5, "H2O": 14.5},
    50: {"CH4": 42.5, "O3": 34.1, "H2O": 34.1},
    100: {"CH4": 98.2, "O3": 58.3, "H2O": 58.3},
}

# Metric conversion factors from pulse emission to future emission scenario (Dietmüller et al., 2022)
ADJUST_COEFF: Final[dict[str, float]] = {
    "CH4": 1.0e-5,
    "O3": 1.0e-5,
    "H2O": 1.0e-5,
    "NOx": 1.0e-5,
}
