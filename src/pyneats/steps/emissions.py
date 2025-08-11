# emissions.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Mapping, Optional, Protocol, cast, runtime_checkable

import pandas as pd
from pycontrails import Flight
from pycontrails.models.emissions import Emissions

__all__ = [
    "DEFAULT_REQUIRED_EMISSION_COLS",
    "FlightWithEmissions",
    "EmissionModel",
    "PyContrailsEmissionParams",
    "PyContrailsEmissionModel",
    "EurocontrolEmissionModel",
    "DLREmissionModel",
    "EmissionModelType",
    "EmissionsStepError",
]

logger = logging.getLogger(__name__)

# ---- configuration ----
DEFAULT_REQUIRED_EMISSION_COLS: Final[tuple[str, ...]] = ("nvpm_ei_m",)


# ---- error type ----
class EmissionsStepError(RuntimeError):
    """Raised when the emissions step fails to evaluate or validate outputs."""


# ---- validated flight view ----
class FlightWithEmissions(Flight):
    """
    A thin, zero-copy *view* of a Flight that guarantees certain emission columns exist.

    Notes
    -----
    - Validation happens in `from_flight()` (not in __init__) to avoid surprising
      failures when upstream libs construct Flights internally.
    - No DataFrame copy: we reuse `flight.data` and `flight.attrs`.
    """

    def __init__(self, data: pd.DataFrame, attrs: dict[str, Any] | None = None) -> None:
        super().__init__(data=data, attrs=attrs)

    @classmethod
    def from_flight(
        cls,
        flight: Flight,
        required_cols: tuple[str, ...] = DEFAULT_REQUIRED_EMISSION_COLS,
    ) -> "FlightWithEmissions":
        """
        Create a validated, zero-copy `FlightWithEmissions` view from an existing `Flight`.

        Parameters
        ----------
        flight : Flight
            The source `Flight` object, expected to already contain the required emission columns.
        required_cols : tuple[str, ...], optional
            The set of emission column names that must be present in `flight`.
            Defaults to `DEFAULT_REQUIRED_EMISSION_COLS`.

        Returns
        -------
        FlightWithEmissions
            A view on the same underlying data/attrs, with type-safe access to emission columns.

        Raises
        ------
        KeyError
            If any of the `required_cols` are missing from the flight data.

        Notes
        -----
        - This method does not copy the DataFrame; it reuses `flight.data` and `flight.attrs`.
        - Use this when you want to ensure the flight is ready for emission-specific processing.
        """
        missing = [c for c in required_cols if c not in flight]
        if missing:
            raise KeyError(f"FlightWithEmissions missing required columns: {missing}")

        return cls(
            data=cast(pd.DataFrame, flight.data),
            attrs=getattr(flight, "attrs", None),
        )

    def has_columns(self, *cols: str) -> bool:
        """
        Check if the flight contains all of the given columns.

        Parameters
        ----------
        *cols : str
            One or more column names to verify.

        Returns
        -------
        bool
            True if all specified columns are present in the flight, False otherwise.
        """
        return all(c in self for c in cols)


# ---- protocol for emissions step ----
@runtime_checkable
class EmissionModel(Protocol):
    """
    An emissions step that enriches a Flight with emissions columns.

    Returning `Flight` keeps composition flexible. Validate with
    `FlightWithEmissions.from_flight()` at boundaries that require it.
    """
    def __call__(self, flight: Flight) -> Flight: ...


# ---- PyContrails Emissions wrapper ----
@dataclass(frozen=True)
class PyContrailsEmissionParams:
    """
    Optional structured params you want to expose explicitly.

    Keep this minimal and stable. Forward everything else via `extra_kwargs`.
    """
    # Example placeholders (uncomment/extend when needed):
    # nvpm_model: str = "SCOPE11"
    # use_fuel_flow: bool = True
    extra_kwargs: Optional[Mapping[str, Any]] = None


class PyContrailsEmissionModel:
    """
    Thin wrapper over `pycontrails.models.emissions.Emissions`.

    - Calls `.eval(source=flight)` to attach emission columns in place.
    - Immediately validates presence of `required_cols` (fail fast).
    - Returns the base `Flight` for pipeline composability.
    """

    def __init__(
        self,
        required_cols: tuple[str, ...] = DEFAULT_REQUIRED_EMISSION_COLS,
        params: PyContrailsEmissionParams | None = None,
    ) -> None:
        self.required_cols = required_cols
        # Merge explicit param bag with direct kwargs (direct kwargs win)
        extra = dict(params.extra_kwargs) if (params and params.extra_kwargs) else {}
        self._impl = Emissions(**extra)

    def __call__(self, flight: Flight) -> Flight:
        # Evaluate emissions via backend
        try:
            out: Flight = self._impl.eval(source=flight)
        except Exception as e:
            logger.exception("Emissions backend evaluation failed")
            raise EmissionsStepError(f"Emissions backend evaluation failed: {e}") from e

        # Validate required columns (zero-copy); raise a clearer domain error
        try:
            _ = FlightWithEmissions.from_flight(out, required_cols=self.required_cols)
        except KeyError as e:
            logger.error("Emissions output missing required columns: %s", e)
            raise EmissionsStepError(f"Emissions output missing required columns: {e}") from e

        logger.info("Emissions step completed successfully")
        return out


# ---- alternative model placeholders ----
class EurocontrolEmissionModel:
    """
    Placeholder for an alternative emissions implementation.

    Implement `__call__` to compute and attach required columns on `flight`
    (prefer vectorized ops), then return `flight`.
    """

    def __init__(self, required_cols: tuple[str, ...] = DEFAULT_REQUIRED_EMISSION_COLS) -> None:
        self.required_cols = required_cols

    def __call__(self, flight: Flight) -> Flight:
        raise NotImplementedError("Eurocontrol Emission Model not yet implemented")


class DLREmissionModel:
    """
    Placeholder for another emissions implementation.

    Same contract as EurocontrolEmissionModel.
    """

    def __init__(self, required_cols: tuple[str, ...] = DEFAULT_REQUIRED_EMISSION_COLS) -> None:
        self.required_cols = required_cols

    def __call__(self, flight: Flight) -> Flight:
        raise NotImplementedError("DLR Emission Model not yet implemented")


# ---- factory enum ----
class EmissionModelType(Enum):
    """
    Factory for emission model implementations.

    Use:
        EmissionModelType.PYCONTRAILS.get(required_cols=("nvpm_ei_m","nox_ei"))
    """
    PYCONTRAILS = PyContrailsEmissionModel
    EUROCONTROL = EurocontrolEmissionModel
    DLR = DLREmissionModel

    def get(self, *args: Any, **kwargs: Any) -> EmissionModel:
        impl = self.value  # type: ignore[assignment]
        return impl(*args, **kwargs)  # type: ignore[misc]
