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
    "DEFAULT_ACCF_KWARGS",
    "DEFAULT_ROCD_PHASE_THRESHOLD",
]

DEFAULT_INTERPOLATOR: Final[str] = "pycontrails"
DEFAULT_TRAJECTORY_PARSER: Final[str] = "nm"
DEFAULT_PERFORMANCE: Final[str] = "bada"
DEFAULT_EMISSIONS: Final[str] = "pycontrails"
DEFAULT_CONTRAILS_MODEL: Final[str] = "cocip"
DEFAULT_NON_CO2_MODEL: Final[str] = "accf"
DEFAULT_CLIMATE_IMPACT: Final[str] = "gwp"

# Trajectory parsing defaults
# Nothing

# Interpolation defaults
DEFAULT_INTERPOLATION_TIME: Final[str] = "1min"

# Performance defaults
DEFAULT_BADA4_VERSION: str = "4.2.1"
DEFAULT_BADA3_VERSION: str = "3.16"

DEFAULT_PAYLOAD_FACTOR: Final[float] = 0.867
DEFAULT_FUEL_RESERVE_FRACTION: Final[float] = 0.03
DEFAULT_MAX_MASS_ESTIMATION_ITER: Final[int] = 2
DEFAULT_MAX_REL_MASS_DIFF: Final[float] = 0.01

DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW: Final[int] = 7
DEFAULT_Q_FUEL: Final[float] = 43_130_000.0

DEFAULT_DELTA_TAU_COMPUTE_METHOD: Final[Literal["point", "zero"]] = "point"
DEFAULT_DELTA_TAU_FILL_METHOD: Final[Literal["bffill", "none", "zero"]] = "bffill"

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
    "interpolation_use_indices": True,  # Note: not specified in document! Default in ModelParams is False
}

# ACCF defaults

DEFAULT_ACCF_KWARGS: Final[Mapping[str, Any]] = {
    "emission_scenario": "pulse",
    "climate_indicator": "ATR",
    "time_horizon": 20,
    "accf_v": "V1.0A",
    "issr_rhi_threshold": 1.0,
    "efficacy": False,
    "forecast_step": 12,
    "PMO": True,
    "pfca": "PCFA-SAC",
    "horizontal_resolution": None,  # Note: Use horizontal resolution of meteorology input data. According to ACCF docs: If None, it will be inferred from the ``met`` dataset for :class:`MetDataset`
    "unit_K_per_kg_fuel": True,  # Note: not specified in document! Default in ACCF is False
}


DEFAULT_ROCD_PHASE_THRESHOLD: Final[float] = 50  # feet per minute
