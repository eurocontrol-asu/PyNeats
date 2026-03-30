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
    Default interpolation time step.
DEFAULT_BADA4_VERSION : str
    Default BADA4 version.
DEFAULT_BADA3_VERSION : str
    Default BADA3 version.
DEFAULT_PAYLOAD_FACTOR : float
    Default payload factor.
DEFAULT_FUEL_RESERVE_FRACTION : float
    Default fuel reserve fraction.
DEFAULT_MAX_MASS_ESTIMATION_ITER : int
    Default max mass estimation iterations.
DEFAULT_MAX_REL_MASS_DIFF : float
    Default max relative mass difference.
DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW : int
    Default smoothing window for true air speed.
DEFAULT_DELTA_TAU_COMPUTE_METHOD : Literal
    Default delta tau compute method.
DEFAULT_DELTA_TAU_FILL_METHOD : Literal
    Default delta tau fill method.
DEFAULT_ROCD_PHASE_THRESHOLD : float
    Default rate of climb/descent phase threshold.
DEFAULT_EMISSIONS_KWARGS : Mapping[str, Any]
    Default emissions model keyword arguments.
DEFAULT_COCIP_KWARGS : Mapping[str, Any]
    Default CoCiP model keyword arguments.
DEFAULT_CLIMACCF_KWARGS : Mapping[str, Any]
    Default ClimAccf model keyword arguments.
DEFAULT_AROMATICS_CONTENT : float
    Default aromatics content for fuel.
DEFAULT_SULPHUR_CONTENT : float
    Default sulphur content for fuel.
DEFAULT_NAPHTHALEN_CONTENT : float
    Default naphthalene content for fuel.
DEFAULT_HYDROGEN_CONTENT : float
    Default hydrogen content for fuel.
REFERENCE_Q_FUEL : float
    Reference q_fuel value.
DEFAULT_Q_FUEL : float
    Default q_fuel value.
OPEN_AIRCLIM_LEVELS : tuple of int
    Default pressure levels for Open Air Clim.
OPEN_AIRCLIM_GRID_RES : float
    Default grid resolution for Open Air Clim.
OPEN_AIRCLIM_COMPUTATION_HORIZON : int
    Default computation horizon for Open Air Clim.
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
    "DEFAULT_DELTA_TAU_COMPUTE_METHOD",
    "DEFAULT_DELTA_TAU_FILL_METHOD",
    "DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW",
    "DEFAULT_EMISSIONS_KWARGS",
    "DEFAULT_COCIP_KWARGS",
    "DEFAULT_CLIMACCF_KWARGS",
    "DEFAULT_ROCD_PHASE_THRESHOLD",
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
DEFAULT_FF_OUTLIER_THRESHOLD = 100

# Mass estimation parameters
# Used in iterative aircraft mass computation from fuel consumption
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

# Fuel burn guardrail: reject if total fuel > (MTOW - OEW) * threshold
# A ratio of 1.1 allows 10% margin above the useful payload capacity
DEFAULT_FUEL_BURN_THRESHOLD: Final[float] = 1.2

# Altitude filter for performance fallback
# Minimum Flight Level (FL) threshold: points below this FL are filtered
# when retrying after a performance step failure.
# FL15 = 2000 ft ≈ 610 m — filters out ground-level / taxi data.
DEFAULT_MIN_ALTITUDE_FL: Final[float] = 20

# Maximum ratio of filtered points before giving up on altitude fallback.
# If more than 80% of trajectory points are below min FL, the flight is
# likely a low-altitude operation — retrying is unlikely to help.
DEFAULT_MAX_ALTITUDE_FILTER_RATIO: Final[float] = 0.8

# Guardrail: reject non-CO2 species producing > MAX_NONCO2_CO2_RATIO × CO2 baseline
MAX_NONCO2_CO2_RATIO: Final[float] = 500.0

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
    "PMO": True,  # Include particulate matter organic (PMO) aerosol effects
    "pfca": "PCFA-SAC",  # Probabilistic fuel consumption approach with SAC radiative forcing
    "horizontal_resolution": None,  # Use native data resolution
    "unit_K_per_kg_fuel": False,  # Output in ATR units (not K per kg fuel)
}
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
    13.79  # 13.79% - Default value provided by consortium (DLR/TO70) for fuel composition
)

# Fuel energy content (specific energy)
# Critical for converting fuel consumption to energy and emissions estimates
REFERENCE_Q_FUEL: Final[float] = (
    43_130_000.0  # J/kg - Baseline value from PyContrails/BADA
)
DEFAULT_Q_FUEL: Final[float] = (
    42_800_000.0  # J/kg - Default value provided by consortium (DLR/TO70)
)


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
