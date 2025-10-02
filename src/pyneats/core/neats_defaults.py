from typing import Final
from typing import Any, Final, Mapping
import numpy as np

__all__ = [
    "DEFAULT_INTERPOLATOR",
    "DEFAULT_TRAJECTORY_PARSER",
    "DEFAULT_PERFORMANCE",
    "DEFAULT_EMISSIONS",
    "DEFAULT_CONTRAILS_MODEL",
    "DEFAULT_NON_CO2_MODEL",
    "DEFAULT_CLIMATE_IMPACT",
    "DEFAULT_INTERPOLATION_TIME",
    "DEFAULT_Q_FUEL",
    "DEFAULT_DELTA_TAU_COMPUTE_METHOD",
    "DEFAULT_DELTA_TAU_FILL_METHOD",
    "DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW",
    "DEFAULT_EMISSIONS_KWARGS",
    "DEFAULT_COCIP_KWARGS",
    "DEFAULT_ACCF_KWARGS",
    "DEFAULT_HORIZONS",
    "DEFAULT_EFFICACY",
    "DEFAULT_SURFACE_EARTH",
    "DEFAULT_SECONDS_PER_YEAR",
    "DEFAULT_AGWP_AR6_WM2YR_PER_KG",
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
DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW: Final[int] = 7
DEFAULT_Q_FUEL: Final[float] = 43_130_000.0

DEFAULT_DELTA_TAU_COMPUTE_METHOD: Final[str] = "zero"
DEFAULT_DELTA_TAU_FILL_METHOD: Final[str] = "bffill"

# Emissions defaults
DEFAULT_EMISSIONS_KWARGS: Final[Mapping[str, Any]] = {}

# Climate defaults
# Cocip defaults

from pycontrails.models.humidity_scaling import (
    ConstantHumidityScaling,
    ExponentialBoostHumidityScaling,
)

DEFAULT_COCIP_KWARGS: Final[Mapping[str, Any]] = {
    "contrail_contrail_overlapping": False,
    "dt_integration": np.timedelta64(1, "m"),
    "max_age": np.timedelta64(12, "h"),
    "humidity_scaling": ExponentialBoostHumidityScaling(
        rhi_adj=0.9779,
        rhi_boost_exponent=1.635,
        clip_upper=1.65,
    ),
    "interpolation_use_indices": True,  # Note: not specified in document! Default in ModelParams is False
}

DEFAULT_COCIP_KWARGS: Final[Mapping[str, Any]] = {
    "dt_integration": np.timedelta64(1, "m"),
    "humidity_scaling": ConstantHumidityScaling(rhi_adj=0.99),
    "interpolation_use_indices": True,
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

DEFAULT_ACCF_KWARGS: Final[Mapping[str, Any]] = {
    "unit_K_per_kg_fuel": True,
    "forecast_step": 12,  # what you used in your snippet
}

# GWP defaults
DEFAULT_HORIZONS: Final[tuple[int, ...]] = (20, 50, 100)
DEFAULT_EFFICACY: Final[float] = 0.42
DEFAULT_SURFACE_EARTH: Final[float] = 5.101e14  # m²
DEFAULT_SECONDS_PER_YEAR: Final[int] = 31_556_952  # s

# AR6 Table 7.SM.7 (W·m⁻²·yr·kg⁻¹) -> convert to J·m⁻²·kg⁻¹ by multiplying by seconds/year
DEFAULT_AGWP_AR6_WM2YR_PER_KG: Mapping[int, float] = {
    20: 0.0243e-12,
    50: 0.0529e-12,  # often ~0.05e-12
    100: 0.0895e-12,
}
