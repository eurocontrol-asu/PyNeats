"""
NEATS Default Parameters Module

This module serves as the single source of truth for all default parameters
used across NEATS pipeline. All parameters described in the RSTS document are
centralized here to ensure configuration consistency, maintainability, and type safety.

Attributes
----------
DEFAULT_INTERPOLATOR : str
    Default interpolator name.
DEFAULT_TRAJECTORY_PARSER : str
    Default trajectory parser name.
DEFAULT_PERFORMANCE : str
    Default performance model name.
DEFAULT_EMISSIONS : str
    Default emissions model name.
DEFAULT_CONTRAILS_MODEL : str
    Default contrails model name.
DEFAULT_NON_CO2_MODEL : str
    Default non-CO2 model name.
DEFAULT_NON_CO2_MODEL_SMALL_EMITTERS : str
    Default non-CO2 model for small emitters.
DEFAULT_CLIMATE_IMPACT : str
    Default climate impact metric.
DEFAULT_INTERPOLATION_TIME : str
    Default interpolation time step, as a pandas frequency string ("1min" = 60 s).
DEFAULT_BADA4_VERSION : str
    Default BADA4 version.
DEFAULT_BADA3_VERSION : str
    Default BADA3 version.
DEFAULT_PAYLOAD_FACTOR : float
    Default payload factor: dimensionless fraction of maximum payload mass.
DEFAULT_FUEL_RESERVE_FRACTION : float
    Default fuel reserve fraction: dimensionless fraction of trip fuel mass.
DEFAULT_MAX_MASS_ESTIMATION_ITER : int
    Default max mass estimation iterations.
DEFAULT_MAX_REL_MASS_DIFF : float
    Default max relative mass difference (dimensionless fraction).
DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW : int
    Default smoothing window for true air speed, in number of points.
DEFAULT_TRUE_AIR_SPEED_SMOOTHING_POLYORDER : int
    Polynomial order of the Savitzky-Golay smoothing of the true air speed.
DEFAULT_DELTA_TAU_COMPUTE_METHOD : Literal
    Default delta tau compute method.
DEFAULT_DELTA_TAU_FILL_METHOD : Literal
    Default delta tau fill method.
DEFAULT_ROCD_PHASE_THRESHOLD : float
    Default rate of climb/descent phase threshold, in ft/min.
DEFAULT_AIRSPEED_STALL_CONFIG : Literal
    Default BADA configuration of the stall speed (at MTOW) below which a
    true airspeed is untrusted.
DEFAULT_MAX_TRUSTED_CAS : float
    Calibrated airspeed above which a true airspeed is untrusted when the BADA
    model has no maximum operating speed VMO (fallback), in m/s.
DEFAULT_MAX_TRUSTED_MACH : float
    Mach number from which a true airspeed is untrusted (dimensionless).
DEFAULT_MAX_UNTRUSTED_AIRSPEED_FRACTION : float
    Maximum fraction of the flight time with an untrusted true airspeed
    (dimensionless fraction [0, 1]); above it the flight fails.
DEFAULT_EMISSIONS_KWARGS : Mapping[str, Any]
    Default emissions model keyword arguments.
DEFAULT_COCIP_KWARGS : Mapping[str, Any]
    Default CoCiP model keyword arguments.
DEFAULT_CLIMACCF_KWARGS : Mapping[str, Any]
    Default ClimAccf model keyword arguments.
DEFAULT_AROMATICS_CONTENT : float
    Default aromatics content for fuel (fraction scale; unused).
DEFAULT_SULPHUR_CONTENT : float
    Default sulphur content for fuel (fraction scale; unused).
DEFAULT_NAPHTHALEN_CONTENT : float
    Default naphthalene content for fuel (fraction scale; unused).
DEFAULT_HYDROGEN_CONTENT : float
    Default hydrogen content for fuel, in wt.% (percent by mass).
REFERENCE_Q_FUEL : float
    Fuel lower calorific value assumed by the BADA fuel flow, in J/kg (the
    BADA4 LHV, 43.217e6; also used for BADA3).
DEFAULT_Q_FUEL : float
    Default q_fuel value, in J/kg (lower calorific value).
Q_FUEL_MIN, Q_FUEL_MAX : float
    Plausible range of a supplied q_fuel, in J/kg (35-50 MJ/kg). A value outside
    it is rejected, which catches a value given in MJ/kg instead of J/kg.
OPEN_AIRCLIM_LEVELS : tuple of int
    Default pressure levels for Open Air Clim, in hPa.
OPEN_AIRCLIM_GRID_RES : float
    Default grid resolution for Open Air Clim, in degrees.
OPEN_AIRCLIM_COMPUTATION_HORIZON : int
    Default computation horizon for Open Air Clim, in years.
OPEN_AIRCLIM_REFERENCE_YEAR : int
    Year in which OpenAirClim (Method D) emits every flight, whatever the
    flight date. The metric window starts in this year.
"""

from collections.abc import Mapping
from typing import Any
from typing import Final
from typing import Literal

import numpy as np


__all__ = [
    "DEFAULT_INTERPOLATOR",
    "DEFAULT_TRAJECTORY_PARSER",
    "DEFAULT_PERFORMANCE",
    "DEFAULT_EMISSIONS",
    "DEFAULT_CONTRAILS_MODEL",
    "DEFAULT_NON_CO2_MODEL",
    "DEFAULT_NON_CO2_MODEL_SMALL_EMITTERS",
    "DEFAULT_CLIMATE_IMPACT",
    "DEFAULT_INTERPOLATION_TIME",
    "DEFAULT_BADA4_VERSION",
    "DEFAULT_Q_FUEL",
    "Q_FUEL_MIN",
    "Q_FUEL_MAX",
    "DEFAULT_DELTA_TAU_COMPUTE_METHOD",
    "DEFAULT_DELTA_TAU_FILL_METHOD",
    "DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW",
    "DEFAULT_TRUE_AIR_SPEED_SMOOTHING_POLYORDER",
    "DEFAULT_EMISSIONS_KWARGS",
    "DEFAULT_COCIP_KWARGS",
    "DEFAULT_CLIMACCF_KWARGS",
    "DEFAULT_ROCD_PHASE_THRESHOLD",
    "DEFAULT_AIRSPEED_STALL_CONFIG",
    "DEFAULT_MAX_TRUSTED_CAS",
    "DEFAULT_MAX_TRUSTED_MACH",
    "DEFAULT_MAX_UNTRUSTED_AIRSPEED_FRACTION",
    "DEFAULT_MIN_ALTITUDE_FL",
    "DEFAULT_MAX_ALTITUDE_FILTER_RATIO",
    "DEFAULT_FUEL_BURN_THRESHOLD",
    "DEFAULT_MAX_PRESSURE_LEVEL",
]  # Public API: All default configuration parameters exported for external use

# Model Selection Defaults
# These parameters specify which implementation/model to use for each pipeline step.
# They determine the concrete model class registered in the steps registry.
DEFAULT_INTERPOLATOR: Final[str] = "pycontrails"
DEFAULT_TRAJECTORY_PARSER: Final[str] = "neats"
DEFAULT_PERFORMANCE: Final[str] = "bada"
DEFAULT_EMISSIONS: Final[str] = "pycontrails"
DEFAULT_CONTRAILS_MODEL: Final[str] = "cocip"
DEFAULT_NON_CO2_MODEL: Final[str] = "local_accf"  # For large emitters
DEFAULT_NON_CO2_MODEL_SMALL_EMITTERS: Final[str] = (
    "open_airclim"  # For small emitters (e.g., regional aviation)
)
DEFAULT_CLIMATE_IMPACT: Final[str] = "gwp"  # Global Warming Potential


# Interpolation defaults
# Specifies the temporal resolution for trajectory
# pandas frequency string passed to Flight.resample_and_fill ("1min" = 60 s)
DEFAULT_INTERPOLATION_TIME: Final[str] = "1min"

# Performance model defaults
# BADA versions determine aircraft performance database and fuel consumption models
# BADA4 is preferred for modern aircraft; BADA3 for legacy aircraft
DEFAULT_BADA4_VERSION: str = "4.2.1"
DEFAULT_BADA3_VERSION: str = "3.16"

# Max consecutive segments of a flight that fall out of the envelope allowed by the BADA model
DEFAULT_BADA_MAX_CONSECUTIVE_FAILURES = 5

# Very conservative threshold on the fuel flow. An error in BADA will be thown if higher
# Further studies need to be performed to better handle out of envelop data points
# Unit: kg/s, whole aircraft; compared only with the BADA-computed fuel flow
# (after the q_fuel correction).
DEFAULT_FF_OUTLIER_THRESHOLD = 100

# Mass estimation parameters
# Used in iterative aircraft mass computation from fuel consumption
# Fraction of the maximum payload mass MPL (MTOW - OEW when MPL is unavailable)
DEFAULT_PAYLOAD_FACTOR: Final[float] = (
    1.0  # Multiplier for expected payload (1.0 = full capacity)
)
DEFAULT_FUEL_RESERVE_FRACTION: Final[float] = (
    0.15  # Following Teoh et al. (2024): 15% reserve fuel requirement
)
DEFAULT_MAX_MASS_ESTIMATION_ITER: Final[int] = (
    4  # Maximum iterations for mass convergence
)
DEFAULT_MAX_REL_MASS_DIFF: Final[float] = (
    0.01  # 1% relative mass difference convergence threshold
)

# Trajectory smoothing parameters
# Applied to true air speed time series to reduce noise from FDIR data
DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW: Final[int] = (
    7  # 7-point rolling window for smoothing
)
# Savitzky-Golay polynomial order (pycontrails segment_true_airspeed and the
# airspeed trust step must use the same value)
DEFAULT_TRUE_AIR_SPEED_SMOOTHING_POLYORDER: Final[int] = 1

# Max pressure level to filter out flights that don't reach the limit altitude to compute climate impact
DEFAULT_MAX_PRESSURE_LEVEL: Final[float] = 550  # hPa

# Delta tau computation parameters
# Used in climb/descent rate estimation and phase detection
DEFAULT_DELTA_TAU_COMPUTE_METHOD: Final[Literal["point", "zero"]] = (
    "point"  # Point-based delta tau calculation
)
DEFAULT_DELTA_TAU_FILL_METHOD: Final[Literal["bffill", "none", "zero"]] = (
    "bffill"  # Backward fill missing values
)

# Rate of climb/descent parameters
# Used to distinguish between climb, cruise, and descent flight phases
DEFAULT_ROCD_PHASE_THRESHOLD: Final[float] = (
    250  # feet per minute threshold for phase detection
)

# Airspeed trust (performance step, before the BADA calculation)
# A row's true airspeed (TAS) is untrusted when it is not finite, when its
# calibrated airspeed (CAS) is below the BADA stall CAS at MTOW in the
# configuration below, or above the aircraft's maximum operating speed VMO
# (BADA, no margin), or when its Mach number is DEFAULT_MAX_TRUSTED_MACH or
# more. No row is removed: an untrusted TAS is replaced by linear interpolation
# in time between the trusted rows.
# Stall configuration: "TO" (take-off) or "LD" (landing).
DEFAULT_AIRSPEED_STALL_CONFIG: Final[Literal["TO", "LD"]] = "TO"
# CAS limit used only when the BADA model has no VMO (fallback); every BADA3
# 3.16 and BADA4 4.2.1 model of the NM sample of 2025-07-09 has one (250 to
# 370 kt).
DEFAULT_MAX_TRUSTED_CAS: Final[float] = 400.0 * 1852.0 / 3600.0  # m/s (400 kt)
# The Mach limit is not the BADA MMO: the computed TAS comes from the ground
# speed and modelled winds (a 10 kt wind error at FL370 is about Mach 0.017),
# so a normal cruise can show a few hundredths above MMO (see the audit, I9).
DEFAULT_MAX_TRUSTED_MACH: Final[float] = 1.0  # dimensionless
# The flight fails when more than this fraction of its time (sum of the
# segment durations, s) has an untrusted TAS, or when no row is trusted.
DEFAULT_MAX_UNTRUSTED_AIRSPEED_FRACTION: Final[float] = 0.8

# Fuel burn guardrail: reject if total fuel > (MTOW - OEW) * threshold
# (masses in kg). A ratio of 1.2 allows a 20% margin above MTOW - OEW.
DEFAULT_FUEL_BURN_THRESHOLD: Final[float] = 1.2

# Altitude filter for performance fallback
# Minimum Flight Level (FL) threshold: points below this FL are filtered
# when retrying after a performance step failure.
# FL20 = 2000 ft = 609.6 m — filters out ground-level / taxi data.
# Converted to m (FL x 100 ft) and compared with the altitude column [m].
DEFAULT_MIN_ALTITUDE_FL: Final[float] = 20

# Maximum ratio of filtered points before giving up on altitude fallback
# (dimensionless fraction [0, 1] of trajectory points).
# If more than 80% of trajectory points are below min FL, the flight is
# likely a low-altitude operation — retrying is unlikely to help.
DEFAULT_MAX_ALTITUDE_FILTER_RATIO: Final[float] = 0.8

# Guardrail: reject non-CO2 species producing > MAX_NONCO2_CO2_RATIO × CO2 baseline
# (dimensionless ratio of CO2-equivalent mass to emitted CO2 mass, both in kg)
MAX_NONCO2_CO2_RATIO: Final[float] = 1000.0

# Emissions model parameters
# Configuration options passed to PyContrails emissions calculation engine
DEFAULT_EMISSIONS_KWARGS: Final[Mapping[str, Any]] = {
    "use_meem": False,  # MEEM (Mission Emissions Estimation Methodology) for NOx - disabled by default
}

# Contrail cirrus impact parameters (CoCiP Model)
# Configuration for ice-supersaturation prediction and contrail evolution modeling
# Humidity scaling method: "Roger's Teoh method" (EAR5 recommendation)
# Note: May not be appropriate for DWD ICON 2-moment microphysics scheme
# See RSTS specification for model tuning parameters
# DEFAULT_HUMIDITY_SCALING = ExponentialBoostHumidityScaling(
#     rhi_adj=0.9779,  # RHI adjustment factor
#     rhi_boost_exponent=1.635,  # Exponential boost coefficient
#     clip_upper=1.65,  # Upper clipping limit for humidity scaling
# )

# Alternative: Disable humidity scaling for DWD ICON datasets
DEFAULT_HUMIDITY_SCALING = None

# CoCiP (Contrails Cirrus Predictions) execution parameters
# Dynamically configured based on humidity scaling configuration above
if DEFAULT_HUMIDITY_SCALING is not None:
    DEFAULT_COCIP_KWARGS: Final[Mapping[str, Any]] = {
        "contrail_contrail_overlapping": False,  # Disable overlapping contrails calculation (performance)
        "dt_integration": np.timedelta64(
            1, "m"
        ),  # 1-minute integration time step for contrail evolution
        "max_age": np.timedelta64(
            12, "h"
        ),  # Maximum contrail age before complete dissipation
        "humidity_scaling": DEFAULT_HUMIDITY_SCALING,  # Apply humidity adjustment from above
        "interpolation_use_indices": False,  # Use direct spatial interpolation (not index-based)
        "vpm_activation": False,  # Disable vpm activation method
    }
else:
    # Fallback configuration without humidity scaling
    DEFAULT_COCIP_KWARGS: Final[Mapping[str, Any]] = {
        "contrail_contrail_overlapping": False,  # Disable overlapping contrails calculation (performance)
        "dt_integration": np.timedelta64(
            1, "m"
        ),  # 1-minute integration time step for contrail evolution
        "max_age": np.timedelta64(
            12, "h"
        ),  # Maximum contrail age before complete dissipation
        "interpolation_use_indices": False,  # Use direct spatial interpolation (not index-based)
        "vpm_activation": False,  # Disable vpm activation
    }

# Aviation Radiative Forcing Index (RFI) and Climate Impact parameters
# ClimAccf uses ACCF (Aviation Radiative Forcing Index-Component Impact Factor) methodology
ACCFS_VERSIONS = Literal["V1.0", "V1.0A"]
DEFAULT_ACCF_VERSION: Final[ACCFS_VERSIONS] = "V1.0A"  # Latest ACCF methodology version

# ClimAccf model configuration
# Computes climate impact factors for CO2, NOx (via aviation induced NOx and ozone), CH4, H2O, and contrails
DEFAULT_CLIMACCF_KWARGS: Final[Mapping[str, Any]] = {
    "emission_scenario": "pulse",  # Pulse emission scenario (vs. continuous background)
    "climate_indicator": "ATR",  # Average Temperature Response (ATR) - to be converted afterwards to GWP
    "time_horizon": 20,  # 20-year time horizon default output from aCCFs
    "accf_v": DEFAULT_ACCF_VERSION,  # Use latest ACCF version specified above
    "issr_rhi_threshold": 1.0,  # RHI threshold for ice-supersaturated region detection
    "efficacy": False,  # Disable efficacy weighting (use direct radiative forcing)
    "forecast_step": 12,  # Use 12-hour meteorological forecast data
    "PMO": True,  # Include primary-mode ozone (PMO, long-term O3 decrease from NOx-driven CH4 loss)
    "pfca": "PCFA-SAC",  # Probabilistic fuel consumption approach with SAC radiative forcing
    "horizontal_resolution": None,  # Use native data resolution
    "unit_K_per_kg_fuel": False,  # Output in ATR units (not K per kg fuel)
}
# Compared with the pycontrails air_pressure column [Pa]; 40000 Pa = 400 hPa
DEFAULT_ACCF_VALIDITY_PRESSURE = 40000  # Pressure level (Pa) for ACCF validity check

# Weather field interpolation configuration
# Defines spatial/temporal boundaries and interpolation methods for meteorological data
InterpolationMethod = Literal["linear", "nearest"]

# Interpolation buffer definitions
# Buffers extend the domain boundaries to prevent edge extrapolation artifacts
DEFAULT_LAT_BUF: Final[tuple[float, float]] = (
    0.0,
    0.0,
)  # (south, north) buffer in degrees
DEFAULT_LON_BUF: Final[tuple[float, float]] = (
    0.0,
    0.0,
)  # (west, east) buffer in degrees
DEFAULT_TIME_BUF: Final[tuple[np.timedelta64, np.timedelta64]] = (
    np.timedelta64(0, "h"),  # Before time step
    np.timedelta64(0, "h"),  # After time step
)
DEFAULT_LEVEL_BUF: tuple[float, float] = (
    0.0,
    40.0,
)  # (lower, upper) pressure buffer in hPa

# Interpolation method selection
DEFAULT_WEATHER_INTEPOLATION_METHOD: Final[InterpolationMethod] = (
    "linear"  # Linear interpolation for smooth fields
)
# CRITICAL: If True, delta_tau (contrail formation parameter) is incorrectly extrapolated below altitude limits
DEFAULT_WEATHER_USE_INDICES: Final[bool] = False


# Jet fuel composition and thermodynamic properties
# Used in emissions and energy calculations. Default values from consortium (DLR/TO70)
# Aromatics, sulphur and naphthalene defaults are fraction scale (0.25 = 25%); the AO
# schema does not define the scale of the corresponding fields. None of the three is
# used in calculations. Hydrogen content is in wt.% (percent by mass), not a fraction.
DEFAULT_AROMATICS_CONTENT: Final[float] = (
    0.25  # 25% - Default value (not used in current calculations)
)
DEFAULT_SULPHUR_CONTENT: Final[float] = (
    0.003  # 0.3% - Default value (not used in current calculations)
)
DEFAULT_NAPHTHALEN_CONTENT: Final[float] = (
    0.03  # 3% - Default value (not used in current calculations)
)
DEFAULT_HYDROGEN_CONTENT: Final[float] = (
    13.79  # wt.% - Default value from consortium (DLR/TO70) for fuel composition
)

# Fuel energy content (specific energy), lower calorific value in J/kg of fuel.
# BADA gives the fuel flow of a fuel with lower calorific value REFERENCE_Q_FUEL
# (pyBADA BADA4: fuel flow = energy flow / LHV of the aircraft file). PyNEATS
# rescales it to the actual fuel: fuel_flow = BADA fuel flow x REFERENCE_Q_FUEL /
# q_fuel. NEATSFuel always carries a q_fuel (DEFAULT_Q_FUEL when none is
# supplied), so this always applies: x 43.217/42.8 = 1.0097 by default.
# REFERENCE_Q_FUEL is the BADA4 4.2.1 LHV: 43.217e6 J/kg in every BADA4 model
# reachable through the PyNEATS mapping tables (86 jets; checked by
# tests/test_fuel_energy_reference.py). BADA3 gives no LHV; the same value is
# used for BADA3 (maintainer decision 2026-10-22, audit A11/A12). Piston models
# (43.71e6) are not used.
REFERENCE_Q_FUEL: Final[float] = 43_217_000.0  # J/kg - BADA4 4.2.1 LHV
# DEFAULT_Q_FUEL is used when neither the AO nor the airport fuel file supplies q_fuel
DEFAULT_Q_FUEL: Final[float] = (
    42_800_000.0  # J/kg - Default value provided by consortium (DLR/TO70)
)
# Plausible range of a supplied q_fuel (AO calorific_value or airport fuel file).
# Jet fuels are about 42.8-43.5 MJ/kg; the range is wide on purpose and only
# catches unit errors: a value in MJ/kg (e.g. 43.05) is 1e6 times too small and
# would make the BADA fuel flow 1e6 times too large.
Q_FUEL_MIN: Final[float] = 35_000_000.0  # J/kg
Q_FUEL_MAX: Final[float] = 50_000_000.0  # J/kg


# OpenAirClim Parameters
# Configuration for Method D climate impact computation for small emitters and regional aviation
# OpenAirClim computes non-CO2 impacts (O3, CH4, H2O, contrail cirrus) via grid-based inventory approach
OPEN_AIRCLIM_LEVELS: Final[tuple[int, ...]] = (
    1000,
    925,
    850,
    700,
    600,
    500,
    400,
    300,
    250,
    200,
    150,
    100,
)  # Pressure levels (hPa) for vertical binning of emissions inventory
OPEN_AIRCLIM_GRID_RES: Final[float] = (
    1.0  # Spatial grid resolution (degrees lat/lon) for emissions aggregation
)
OPEN_AIRCLIM_COMPUTATION_HORIZON: Final[int] = (
    100  # Time horizon (years) for AGWP computation
)
# Method D treats every flight as a pulse emitted in this year, whatever the
# flight date, so the same flight gives the same result in any calendar year.
# The inventory year, the metric start year (t_0), the simulated time range and
# the result read back (AGWP_{H}_{year}) all use it. It must be a year covered
# by the base inventory (ELK_aviation_2025, i.e. 2025). Changing it changes the
# background concentrations and therefore the results.
OPEN_AIRCLIM_REFERENCE_YEAR: Final[int] = 2025
