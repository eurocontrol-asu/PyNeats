# contrails.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final, Mapping, Protocol, runtime_checkable
import numpy as np


from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.models.cocip import Cocip
from pycontrails.models.humidity_scaling import ConstantHumidityScaling


from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.core.steps import Step, BaseStep
from pyneats.core.steps_registry import register

__all__ = ["ContrailsStepError",
    "FlightWithContrailsImpact",
    "ContrailsModel",
    "ContrailsParams",
    "CoCiPModel",
]   

logger = logging.getLogger(__name__)

# Sensible, overridable defaults for Cocip(...)
DEFAULT_COCIP_KWARGS: Final[Mapping[str, Any]] = {
    "dt_integration": np.timedelta64(1, "m"),
    "humidity_scaling": ConstantHumidityScaling(rhi_adj=0.99),
}

# ---- configuration -------------------------------------------------
# Keep minimal; expand as you standardize schema 
# ef : effective radiative forcing (W/m^2)
DEFAULT_REQUIRED_CONTRAIL_COLS: Final[tuple[str, ...]] = ("ef", ) 

# ---- error type ----------------------------------------------------
class ContrailsStepError(RuntimeError):
    """Raised when contrail impact evaluation fails or yields invalid output."""


class FlightWithContrailsImpact(FlightWithEmissions):
    """Zero-copy typed view for emissions-enriched flights."""
    REQUIRED = DEFAULT_REQUIRED_CONTRAIL_COLS

@runtime_checkable
class ContrailsModel(Step[FlightWithEmissions, FlightWithContrailsImpact], Protocol):
    """
    Emission steps consume a performance-enriched flight and produce
    an emissions-enriched flight (zero-copy typed view).
    """
    # def __call__(self, flight: FlightWithEmissions) -> FlightWithContrailsImpact: ...



# ---- params --------------------------------------------------------
@dataclass(frozen=True)
class ContrailsParams:
    met: MetDataset | None = None
    rad: MetDataset | None = None
    cocip_kwargs: Mapping[str, Any] = field(default_factory=dict)  # never None

    def __post_init__(self) -> None:  # type: ignore[override]
        # dataclasses with frozen=True don't run __post_init__ for mutation; we just ensure defaults are dict-like at use time
        pass


# ---- PyContrails COCIP wrapper ------------------------------------
@register(ContrailsModel, "cocip")
class CoCiPModel(BaseStep[FlightWithEmissions, FlightWithContrailsImpact]):
    def __init__(
        self,
        params: ContrailsParams,
        required_cols: tuple[str, ...] = DEFAULT_REQUIRED_CONTRAIL_COLS,
        interpolation_use_indices: bool = True,
    ) -> None:
        # IMPORTANT: initialize BaseStep internals (incl. logger)
        super().__init__()                       # <-- add this
        self.logger = logging.getLogger(__name__)  # <-- and keep a logger on self

        if params.met is None or params.rad is None:
            raise ContrailsStepError("COCIP requires both 'met' and 'rad' datasets.")

        self.required_cols = required_cols
        cocip_args = dict(DEFAULT_COCIP_KWARGS)
        cocip_args.update(params.cocip_kwargs)

        try:
            self._impl = Cocip(
                met=params.met,
                rad=params.rad,
                params=cocip_args,
                interpolation_use_indices=interpolation_use_indices,
            )
        except Exception as e:
            self.logger.exception("Failed to initialize COCIP model")
            raise ContrailsStepError(f"COCIP initialization failed: {e}") from e

    def run(self, flight: FlightWithEmissions) -> FlightWithContrailsImpact:
        try:
            out: Flight = self._impl.eval(source=flight)
        except Exception as e:
            self.logger.exception("COCIP evaluation failed")
            raise ContrailsStepError(f"COCIP evaluation failed: {e}") from e

        self.logger.info("COCIP step completed successfully")
        return FlightWithContrailsImpact.from_flight(out, require=self.required_cols)