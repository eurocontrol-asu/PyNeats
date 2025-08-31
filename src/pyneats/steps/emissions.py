# steps/emissions.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Mapping, Optional, runtime_checkable, Protocol

from pycontrails import Flight
from pycontrails.models.emissions import Emissions

from pyneats.core.steps import BaseStep, Step, StepError
from pyneats.core.views import FlightView
from pyneats.steps.performance import FlightWithPerformance  # <- strong input type


__all__ = [
    "DEFAULT_REQUIRED_EMISSION_COLS",
    "FlightWithEmissions",
    "EmissionsStepError",
    "EmissionModel",
    "PyContrailsEmissionParams",
    "PyContrailsEmissionModel",
    "EurocontrolEmissionModel",
    "DLREmissionModel"
]


logger = logging.getLogger(__name__)

# ---- views ----
DEFAULT_REQUIRED_EMISSION_COLS: Final[tuple[str, ...]] = ("nvpm_ei_m",)

class FlightWithEmissions(FlightView):
    REQUIRED = DEFAULT_REQUIRED_EMISSION_COLS


# ---- error type ----
class EmissionsStepError(StepError):
    """Normalized domain error for the emissions step."""


# ---- protocol: strong contract (Perf -> Emissions) ----
@runtime_checkable
class EmissionModel(Step[FlightWithPerformance, FlightWithEmissions], Protocol):
    """
    Emission steps consume a performance-enriched flight and produce
    an emissions-enriched flight (zero-copy view).
    """
    # Protocol is inherited from Step:  def __call__(self, flight: In) -> Out: ...


# ---- params bag ----
@dataclass(frozen=True)
class PyContrailsEmissionParams:
    extra_kwargs: Optional[Mapping[str, Any]] = None


# ---- concrete implementation ----
class PyContrailsEmissionModel(BaseStep[FlightWithPerformance, FlightWithEmissions]):
    """
    Thin wrapper over pycontrails.Emissions:
    - input:  FlightWithPerformance (validated upstream)
    - output: FlightWithEmissions (validated here, zero-copy)
    """

    def __init__(
        self,
        required_cols: tuple[str, ...] = DEFAULT_REQUIRED_EMISSION_COLS,
        params: PyContrailsEmissionParams | None = None,
    ) -> None:
        super().__init__()
        self.required_cols = required_cols
        extra = dict(params.extra_kwargs) if (params and params.extra_kwargs) else {}
        self._impl = Emissions(**extra)

    def run(self, flight: FlightWithPerformance) -> FlightWithEmissions:
        try:
            # pycontrails returns the same Flight with columns attached
            out: Flight = self._impl.eval(flight)
        except Exception as e:
            raise EmissionsStepError(type(self).__name__, f"backend eval failed: {e}") from e

        # Validate schema and return the *typed view* (zero-copy)
        return FlightWithEmissions.from_flight(out, require=self.required_cols)


# ---- placeholders for other implementations ----
class EurocontrolEmissionModel(BaseStep[FlightWithPerformance, FlightWithEmissions]):
    def __init__(self, required_cols: tuple[str, ...] = DEFAULT_REQUIRED_EMISSION_COLS) -> None:
        super().__init__()
        self.required_cols = required_cols

    def run(self, flight: FlightWithPerformance) -> FlightWithEmissions:
        raise EmissionsStepError(type(self).__name__, "not implemented")


class DLREmissionModel(BaseStep[FlightWithPerformance, FlightWithEmissions]):
    def __init__(self, required_cols: tuple[str, ...] = DEFAULT_REQUIRED_EMISSION_COLS) -> None:
        super().__init__()
        self.required_cols = required_cols

    def run(self, flight: FlightWithPerformance) -> FlightWithEmissions:
        raise EmissionsStepError(type(self).__name__, "not implemented")


# ---- factory enum (kept for now) ----
class EmissionModelType(Enum):
    PYCONTRAILS = PyContrailsEmissionModel
    EUROCONTROL = EurocontrolEmissionModel
    DLR = DLREmissionModel

    def get(self, *args: Any, **kwargs: Any) -> EmissionModel:
        impl = self.value  # type: ignore[assignment]
        return impl(*args, **kwargs)  # type: ignore[misc]
