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
    Number of seconds in a year: 31,536,000 s = 365 d, as in
    docs/explanation/mrv-specification.md (s_yr). Was 31,556,952 s (365.2425 d,
    Gregorian mean year) before decision C.16 (2026-10-28, see
    docs/internal/pyneats_units_audit.md).
SOLAR_CONSTANT : float
    Solar constant in W m^-2.
PVU_PER_SI : float
    Potential vorticity units per SI unit of potential vorticity
    (1 PVU = 1e-6 K m^2 kg^-1 s^-1).
CO2_AGWP_COEFF_WM2YR_PER_KG : Mapping[int, float]
    CO2 AGWP coefficients C(H) in W m-2 yr per kg CO2, keyed by horizon in
    years: 24.16 / 47.57 / 74.36e-15, as in
    docs/explanation/mrv-specification.md. Was 24.12 / 47.50 / 74.24e-15 before
    decision C.16.
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
PMO_CH4_RF_RATIO : float
    PMO / CH4 radiative-forcing ratio (dimensionless, 0.29).
ACCF_SCALE_03 : Mapping[str, float]
    Scaling factors for O3 ACCFs (divisors), keyed by aCCF version.
ACCF_SCALE_CH4 : Mapping[str, float]
    Scaling factors for CH4 ACCFs (divisors), keyed by aCCF version.
ACCF_SCALE_H2O : Mapping[str, float]
    Scaling factors for H2O ACCFs (divisors), keyed by aCCF version.
SCALING_TO_BASELINE_2026_METHOD_C : Mapping[str, float | None]
    Method C divisors of the "scaling_to_baseline_2026" non-CO2 scaling, keyed
    by species (None = not set yet).
SCALING_TO_BASELINE_2026_METHOD_D : Mapping[str, float | None]
    Method D divisors of the "scaling_to_baseline_2026" non-CO2 scaling, keyed
    by species (None = not set yet).
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
    "SCALING_TO_BASELINE_2026_METHOD_C",
    "SCALING_TO_BASELINE_2026_METHOD_D",
    "RF_BACKWARD_FACTOR",
    "PMO_CH4_RF_RATIO",
]

METRICS_HORIZONS: Final[tuple[int, ...]] = (20, 50, 100)
SURFACE_EARTH: Final[float] = 5.101e14  # m²
# s_yr of the MRV specification (docs/explanation/mrv-specification.md, sect.
# 3.7.1): 365 d. Used as s/yr to turn contrail energy forcing [J] into EAGWP
# [W m-2 yr]. Was 31_556_952 s (365.2425 d, Gregorian mean year) until decision
# C.16 (Ramon and Philippe, 2026-10-28: "use the DOC values"); the change makes
# contrail EAGWP 0.066 % larger (31_556_952 / 31_536_000).
SECONDS_PER_YEAR: Final[int] = 31_536_000  # s
SOLAR_CONSTANT: Final[float] = 1360.0  # [W m^-2]
# [PVU per K m^2 kg^-1 s^-1]: PV[PVU] = PV[SI] * PVU_PER_SI (1 PVU = 1e-6 SI)
PVU_PER_SI: Final[float] = 1e6

# CO2 AGWP coefficients C(H) from AirClim (Dahlmann et al., 2025), as listed in
# the MRV specification (docs/explanation/mrv-specification.md, sect. 3.7.1).
# C(H) in W·m⁻²·yr·kg⁻¹ (per kgCO2); keys are horizons in years.
# Commit bf3aa7b had changed them to 24.12 / 47.50 / 74.24e-15; decision C.16
# (Ramon and Philippe, 2026-10-28: "use the DOC values") restored the
# specification values (see docs/internal/pyneats_units_audit.md). Non-CO2
# CO2eq = EAGWP / C(H) is 0.15-0.17 % smaller than with the bf3aa7b values.
CO2_AGWP_COEFF_WM2YR_PER_KG: Mapping[int, float] = {
    20: 24.16e-15,
    50: 47.57e-15,
    100: 74.36e-15,
}

# New generic conversion factors to convert RF to AGWP or ATR
# (Dahlmann et al., 2025) for Pulse 2025 scenario
# Absolute units are not stated here and not verified. gwp.py uses only the ratio
# k_AGWP(H) / k_ATR(H0), combined with efficacy**2 / RF_BACKWARD_FACTOR, to map
# ATR [K] to EAGWP [W m-2 yr], so that combined scale must carry W m-2 yr per K.
CONVERSION_FACTORS_AGWP_TO_RF: Final[dict[int, dict[str, float]]] = {
    20: {"CH4": 10.6318, "O3": 1.0192, "H2O": 1.0192, "PMO": 10.6318},
    50: {"CH4": 13.0968, "O3": 1.0192, "H2O": 1.0192, "PMO": 13.0968},
    100: {"CH4": 13.3563, "O3": 1.0192, "H2O": 1.0192, "PMO": 13.3563},
}
CONVERSION_FACTORS_ATR_TO_RF: Final[dict[int, dict[str, float]]] = {
    20: {"CH4": 0.2838, "O3": 0.0337, "H2O": 0.032, "PMO": 0.269},
    50: {"CH4": 0.1898, "O3": 0.0154, "H2O": 0.0146, "PMO": 0.18},
    100: {"CH4": 0.1059, "O3": 0.0082, "H2O": 0.0078, "PMO": 0.1004},
}


# Efficacies as specified in the RSTS document (coming from AirClim).
# PMO (primary-mode ozone, the long-term O3 decrease that follows the NOx-driven
# CH4 decrease): 1.0 is the RSTS value, confirmed by the method owner 2026-10-28.
# gwp.py applies it to the PMO part only, which is then added into the "CH4"
# output entry (see docs/explanation/mrv-specification.md).
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
# PMO has the CH4 value: in Method C its ATR is derived from the CH4 aCCF
# (ATR_PMO = PMO_CH4_RF_RATIO x ATR_CH4), so it carries the same aCCF scaling.
RF_BACKWARD_FACTOR: Final[dict[str, float]] = {
    "CH4": 0.492,
    "O3": 0.508,
    "H2O": 0.52,
    "PMO": 0.492,
}

# PMO / CH4 radiative-forcing ratio [dimensionless]: PMO RF = 0.29 x CH4 RF.
# Source: CLIMaCCF (aCCF CH4 x 1.29 when PMO is on) and OpenAirClim
# calc_ch4.py:217 (v0.13.0). local_accf.py uses it to write ATR_20_PMO.
PMO_CH4_RF_RATIO: Final[float] = 0.29

# ACCFs scaling factors, keyed by aCCF version; local_accf divides the aCCF output
# by them
ACCF_SCALE_03: Final[Mapping[str, float]] = {"V1.0": 1.97, "V1.0A": 11.0}
ACCF_SCALE_CH4: Final[Mapping[str, float]] = {"V1.0": 2.03, "V1.0A": 35.0}
ACCF_SCALE_H2O: Final[Mapping[str, float]] = {"V1.0": 1.92, "V1.0A": 3.0}

# Non-CO2 scaling "scaling_to_baseline_2026" (DLR, 2026): Method D is aligned
# with Lee et al. on a global inventory (D*), then Method C with D* on the MRV
# regional perimeter (C*). O3, CH4, PMO and H2O each have a value; contrails
# are not scaled.
#
# PROVISIONAL inputs, not for results (given by Philippe, 2026-11-27). Both
# are multipliers:
# - D to Lee et al.: multiplier of the OpenAirClim output, from Bruder et al.
# - C to D: Method D / Method C on a sample, both with the "accf_version"
#   scaling (aCCF V1.0A). The CH4 value is also used for PMO.
_BASELINE_2026_D_TO_LEE: Final[Mapping[str, float]] = {
    "O3": 0.60,
    "CH4": 1.06,
    "PMO": 1.83,
    "H2O": 2.38,
}
_BASELINE_2026_C_TO_D: Final[Mapping[str, float]] = {
    "O3": 0.889056,
    "CH4": 2.316996,
    "PMO": 2.316996,
    "H2O": 1.480933,
}
# What Method C divides by under the "accf_version" scaling with aCCF V1.0A:
# ACCF_SCALE_*["V1.0A"] x RF_BACKWARD_FACTOR (O3 5.588, CH4 and PMO 17.22,
# H2O 1.56). PMO carries the CH4 aCCF scale (ATR_PMO = 0.29 x ATR_CH4).
_ACCF_V10A_DIVISOR: Final[Mapping[str, float]] = {
    "O3": ACCF_SCALE_03["V1.0A"] * RF_BACKWARD_FACTOR["O3"],
    "CH4": ACCF_SCALE_CH4["V1.0A"] * RF_BACKWARD_FACTOR["CH4"],
    "PMO": ACCF_SCALE_CH4["V1.0A"] * RF_BACKWARD_FACTOR["PMO"],
    "H2O": ACCF_SCALE_H2O["V1.0A"] * RF_BACKWARD_FACTOR["H2O"],
}

# The values the code applies. All are divisors, keyed by species. A table
# without a "PMO" entry uses the CH4 value for PMO (core/non_co2_scaling.py).
# None = value not given yet: a run with this scaling stops at start-up.
# - Method C: divisor of the raw aCCF regression. It replaces both
#   ACCF_SCALE_*[accf_v] (local_accf.py) and RF_BACKWARD_FACTOR (gwp.py), which
#   is 1.0 under this scaling: C* = C x (C to D) x (D to Lee et al.), so the
#   divisor is the "accf_version" one over these two multipliers. The PMO
#   divisor sets ATR_PMO = 0.29 x ATR_CH4 x (CH4 divisor / PMO divisor).
# - Method D: divisor of the OpenAirClim AGWP (open_airclim.py), 1 over the
#   multiplier; the "accf_version" scaling applies none.
SCALING_TO_BASELINE_2026_METHOD_C: Final[Mapping[str, float | None]] = {
    sp: _ACCF_V10A_DIVISOR[sp] / (_BASELINE_2026_C_TO_D[sp] * m)
    for sp, m in _BASELINE_2026_D_TO_LEE.items()
}
SCALING_TO_BASELINE_2026_METHOD_D: Final[Mapping[str, float | None]] = {
    sp: 1.0 / m for sp, m in _BASELINE_2026_D_TO_LEE.items()
}

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
