"""
Physical and Radiative Constants for Climate Impact Calculations

This module defines constants used in climate impact calculations, including
metrics horizons, surface area, radiative forcing coefficients, and scaling factors.

Attributes
----------
METRICS_HORIZONS : tuple of int
    Supported time horizons for metrics, in years.
SURFACE_EARTH : float
    Surface area of the Earth in m².
SECONDS_PER_YEAR : int
    Number of seconds in a year: 31,556,952 s = 365.2425 d (Gregorian mean
    year). docs/explanation/mrv-specification.md uses 31,536,000 s (365 d)
    (see docs/internal/pyneats_units_audit.md).
SOLAR_CONSTANT : float
    Solar constant in W m^-2.
PVU_PER_SI : float
    Potential vorticity units per SI unit of potential vorticity
    (1 PVU = 1e-6 K m^2 kg^-1 s^-1).
CO2_AGWP_COEFF_WM2YR_PER_KG : Mapping[int, float]
    CO2 AGWP coefficients C(H) in W m-2 yr per kg CO2, keyed by horizon in
    years.
CONVERSION_FACTORS_AGWP_TO_RF : dict
    Conversion factors from RF to AGWP(H) (Dahlmann et al., 2025; the name
    reads the other way), keyed by horizon in years and species. Absolute
    units not verified.
CONVERSION_FACTORS_ATR_TO_RF : dict
    Conversion factors from RF to ATR(H) (Dahlmann et al., 2025; the name
    reads the other way), keyed by horizon in years and species. Absolute
    units not verified.
EFFICACY : dict
    Efficacy values for different species (dimensionless).
RF_BACKWARD_FACTOR : dict
    Backward calculation factors for radiative forcing (divisors).
ACCF_SCALE_03 : Mapping[str, float]
    Scaling factors for O3 ACCFs (divisors), keyed by aCCF version.
ACCF_SCALE_CH4 : Mapping[str, float]
    Scaling factors for CH4 ACCFs (divisors), keyed by aCCF version.
ACCF_SCALE_H2O : Mapping[str, float]
    Scaling factors for H2O ACCFs (divisors), keyed by aCCF version.
DEFAULT_PRESSURE_LEVELS_HPA : tuple of float
    Default pressure levels in hPa.
"""

from collections.abc import Mapping
from typing import Final


__all__ = [
    "METRICS_HORIZONS",
    "SURFACE_EARTH",
    "SECONDS_PER_YEAR",
    "CO2_AGWP_COEFF_WM2YR_PER_KG",
    "CONVERSION_FACTORS_AGWP_TO_RF",
    "CONVERSION_FACTORS_ATR_TO_RF",
    "EFFICACY",
    "SOLAR_CONSTANT",
    "PVU_PER_SI",
    "ACCF_SCALE_03",
    "ACCF_SCALE_CH4",
    "ACCF_SCALE_H2O",
    "RF_BACKWARD_FACTOR",
]

METRICS_HORIZONS: Final[tuple[int, ...]] = (20, 50, 100)
SURFACE_EARTH: Final[float] = 5.101e14  # m²
# Gregorian mean year (365.2425 d); used as s/yr to turn contrail energy forcing
# [J] into EAGWP [W m-2 yr]
SECONDS_PER_YEAR: Final[int] = 31_556_952  # s
SOLAR_CONSTANT: Final[float] = 1360.0  # [W m^-2]
# [PVU per K m^2 kg^-1 s^-1]: PV[PVU] = PV[SI] * PVU_PER_SI (1 PVU = 1e-6 SI)
PVU_PER_SI: Final[float] = 1e6

# CO2 GWP coefficients from AirClim (Dahlmann et al., 2025)
# C(H) in W·m⁻²·yr·kg⁻¹ (per kgCO2); keys are horizons in years.
# Values from commit bf3aa7b; docs/explanation/mrv-specification.md still lists
# the older 24.16 / 47.57 / 74.36e-15 (see docs/internal/pyneats_units_audit.md).
CO2_AGWP_COEFF_WM2YR_PER_KG: Mapping[int, float] = {
    20: 24.12e-15,
    50: 47.50e-15,
    100: 74.24e-15,
}

# New generic conversion factors to convert RF to AGWP or ATR
# (Dahlmann et al., 2025) for Pulse 2025 scenario
# Absolute units are not stated here and not verified. gwp.py uses only the ratio
# k_AGWP(H) / k_ATR(H0), combined with efficacy**2 / RF_BACKWARD_FACTOR, to map
# ATR [K] to EAGWP [W m-2 yr], so that combined scale must carry W m-2 yr per K.
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

# Historical RF backward calculation factor implicitly used in
# Dietmuller et al., 2023 and Yin et al., 2023
# Not necessary anymore while using modern conversion factors from
# Dahlmann et al., 2025
# Therefore used here to discount accf output value before applying
# conversion factors from Dahlmann et al., 2025
# Used as a divisor in gwp.py. The values are approximately 1 / ACCF_SCALE_*["V1.0"]
# (1/1.97 = 0.508, 1/2.03 = 0.493, 1/1.92 = 0.521), so the two tables are coupled.
RF_BACKWARD_FACTOR: Final[dict[str, float]] = {
    "CH4": 0.492,
    "O3": 0.508,
    "H2O": 0.52,
}

# ACCFs scaling factors, keyed by aCCF version; local_accf divides the aCCF output
# by them
ACCF_SCALE_03: Final[Mapping[str, float]] = {"V1.0": 1.97, "V1.0A": 11.0}
ACCF_SCALE_CH4: Final[Mapping[str, float]] = {"V1.0": 2.03, "V1.0A": 35.0}
ACCF_SCALE_H2O: Final[Mapping[str, float]] = {"V1.0": 1.92, "V1.0A": 3.0}

# Pressure levels in hPa
DEFAULT_PRESSURE_LEVELS_HPA: Final[tuple[float, ...]] = (
    550,
    500,
    450,
    400,
    350,
    300,
    250,
    225,
    200,
    175,
    150,
    125,
)
