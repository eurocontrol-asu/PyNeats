from typing import Final

__all__ = [
    "DEFAULT_INTERPOLATOR",
    "DEFAULT_TRAJECTORY_PARSER",
    "DEFAULT_PERFORMANCE",
    "DEFAULT_EMISSIONS",
    "DEFAULT_CONTRAILS_MODEL",
    "DEFAULT_NON_CO2_MODEL",
    "DEFAULT_CLIMATE_IMPACT",
]

DEFAULT_INTERPOLATOR: Final[str] = "pycontrails"
DEFAULT_TRAJECTORY_PARSER: Final[str] = "nm"
DEFAULT_PERFORMANCE: Final[str] = "bada"
DEFAULT_EMISSIONS: Final[str] = "pycontrails"
DEFAULT_CONTRAILS_MODEL: Final[str] = "cocip"
DEFAULT_NON_CO2_MODEL: Final[str] = "accf"
DEFAULT_CLIMATE_IMPACT: Final[str] = "gwp"
