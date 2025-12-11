"""NEATS Default Parameters Module

This module serves as the single source of truth for all default parameters used across
NEATS pipeline. All parameters described in the RSTS  document are centralized here to ensure:

* Configuration Consistency
   - No hardcoded parameters exist in computation modules
   - All defaults are documented and maintainable in one location
   - Changes to defaults only need to be made here

* Parameter Categories
   - Trajectory parsing parameters
   - Interpolation settings
   - Performance model configuration (BADA3/4)
   - Emissions calculation parameters
   - Weather data processing settings
   - Climate impact models configuration
     * CoCiP (Contrail Cirrus Prediction)
     * ACCF (Algorithmic Climate Change Functions)
   - Fuel properties defaults

* Type Safety
   - All parameters are typed using Final type hints

* Parameter Customization:
   While this module defines default values, each processing step can be customized
   by overloading its specific parameter class

"""

from typing import Final
from typing import Any, Mapping, Literal
import numpy as np
from pycontrails.models.humidity_scaling import (
    ExponentialBoostHumidityScaling,
)

__all__ = [
    "DEFAULT_INTERPOLATOR",
    "DEFAULT_TRAJECTORY_PARSER",
    "DEFAULT_PERFORMANCE",
    "DEFAULT_EMISSIONS",
    "DEFAULT_CONTRAILS_MODEL",
    "DEFAULT_NON_CO2_MODEL",
    "DEFAULT_CLIMATE_IMPACT",
    "DEFAULT_INTERPOLATION_TIME",
    "DEFAULT_BADA4_VERSION",
    "DEFAULT_BADA4_VERSION",
    "DEFAULT_Q_FUEL",
    "DEFAULT_DELTA_TAU_COMPUTE_METHOD",
    "DEFAULT_DELTA_TAU_FILL_METHOD",
    "DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW",
    "DEFAULT_EMISSIONS_KWARGS",
    "DEFAULT_COCIP_KWARGS",
    "DEFAULT_CLIMACCF_KWARGS",
    "DEFAULT_ROCD_PHASE_THRESHOLD",
]

DEFAULT_INTERPOLATOR: Final[str] = "pycontrails"
DEFAULT_TRAJECTORY_PARSER: Final[str] = "neats"
DEFAULT_PERFORMANCE: Final[str] = "bada"
DEFAULT_EMISSIONS: Final[str] = "pycontrails"
DEFAULT_CONTRAILS_MODEL: Final[str] = "cocip"
DEFAULT_NON_CO2_MODEL: Final[str] = "local_accf"
DEFAULT_CLIMATE_IMPACT: Final[str] = "gwp"


# Interpolation defaults
DEFAULT_INTERPOLATION_TIME: Final[str] = "1min"

# Performance defaults
DEFAULT_BADA4_VERSION: str = "4.2.1"
DEFAULT_BADA3_VERSION: str = "3.16"

DEFAULT_PAYLOAD_FACTOR: Final[float] = 1.0
DEFAULT_FUEL_RESERVE_FRACTION: Final[float] = 0.03
DEFAULT_MAX_MASS_ESTIMATION_ITER: Final[int] = 4
DEFAULT_MAX_REL_MASS_DIFF: Final[float] = 0.01

DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW: Final[int] = 7
DEFAULT_Q_FUEL: Final[float] = 43_130_000.0

DEFAULT_DELTA_TAU_COMPUTE_METHOD: Final[Literal["point", "zero"]] = "point"
DEFAULT_DELTA_TAU_FILL_METHOD: Final[Literal["bffill", "none", "zero"]] = "bffill"

DEFAULT_ROCD_PHASE_THRESHOLD: Final[float] = 250  # feet per minute

# Emissions defaults
DEFAULT_EMISSIONS_KWARGS: Final[Mapping[str, Any]] = {}

# Cocip default arguments
DEFAULT_HUMIDITY_SCALING = ExponentialBoostHumidityScaling(
    rhi_adj=0.9779,
    rhi_boost_exponent=1.635,
    clip_upper=1.65,
)

DEFAULT_COCIP_KWARGS: Final[Mapping[str, Any]] = {
    "contrail_contrail_overlapping": False,
    "dt_integration": np.timedelta64(1, "m"),
    "max_age": np.timedelta64(12, "h"),
    "humidity_scaling": DEFAULT_HUMIDITY_SCALING,
    "interpolation_use_indices": False,  
}

# ACCF defaults

ACCFS_VERSIONS = Literal["V1.0", "V1.0A"]
DEFAULT_ACCF_VERSION: Final[ACCFS_VERSIONS] = "V1.0A"

DEFAULT_CLIMACCF_KWARGS: Final[Mapping[str, Any]] = {
    "emission_scenario": "pulse",
    "climate_indicator": "ATR",
    "time_horizon": 20,
    "accf_v": DEFAULT_ACCF_VERSION,
    "issr_rhi_threshold": 1.0,
    "efficacy": False,
    "forecast_step": 12,
    "PMO": True,
    "pfca": "PCFA-SAC",
    "horizontal_resolution": None,
    "unit_K_per_kg_fuel": False
}

# Weather interpolation defaults

InterpolationMethod = Literal["linear", "nearest"]

DEFAULT_LAT_BUF: Final[tuple[float, float]] = (0.0, 0.0)
DEFAULT_LON_BUF:  Final[tuple[float, float]] = (0.0, 0.0)
DEFAULT_TIME_BUF: Final[tuple[np.timedelta64, np.timedelta64]] = (
        np.timedelta64(0, "h"),
        np.timedelta64(0, "h"),
    )
DEFAULT_LEVEL_BUF: tuple[float, float] = (0.0, 0.0)

DEFAULT_WEATHER_INTEPOLATION_METHOD: Final[InterpolationMethod] = "linear"
DEFAULT_WEATHER_USE_INDICES: Final[bool] = False # Important. If True, delta_tau is wrongly extrapolated bellow the limit altitude


# Default Fuel constants

DEFAULT_AROMATICS_CONTENT : Final[float] = 0.25  # default value - Not used in calculations
DEFAULT_SULPHUR_CONTENT : Final[float] = 0.003   # default value - Not used in calculations
DEFAULT_NAPHTHALEN_CONTENT : Final[float] = 0.03 # default value - Not used in calculations


