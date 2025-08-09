from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Any, Final, cast, Optional, Dict
from enum import Enum
import inspect
import pandas as pd

from pycontrails import Flight
from pycontrails.models.emissions import Emissions

# ---- configuration ----
# Default set is minimal; extend per use-case when constructing the model.
DEFAULT_REQUIRED_EMISSION_COLS: Final[tuple[str, ...]] = ("nvpm_ei_m",)


# ---- validated flight type ----
class FlightWithEmissions(Flight):
    """
    A Flight guaranteed to contain the requested emission columns.

    Notes on performance:
    - Validates presence of required columns only (O(#cols)); no DataFrame copy.
    - `from_flight` reuses the underlying data; no large allocations.
    """

    def __init__(
        self,
        data: pd.DataFrame,
        attrs: dict[str, Any] | None = None,
        required_cols: tuple[str, ...] = DEFAULT_REQUIRED_EMISSION_COLS,
    ) -> None:
        super().__init__(data=data, attrs=attrs)
        missing = [c for c in required_cols if c not in self]
        if missing:
            raise KeyError(f"FlightWithEmissions missing required columns: {missing}")

    @classmethod
    def from_flight(
        cls,
        flight: Flight,
        required_cols: tuple[str, ...] = DEFAULT_REQUIRED_EMISSION_COLS,
    ) -> FlightWithEmissions:
        """
        Wrap an existing Flight in a FlightWithEmissions without copying data.

        Parameters
        ----------
        flight : Flight
            Existing Flight object to wrap.
        required_cols : tuple[str, ...], optional
            Names of emission columns that must be present in the Flight.

        Returns
        -------
        FlightWithEmissions
            A validated wrapper around the original Flight data.

        Raises
        ------
        KeyError
            If any of the required emission columns are missing.

        Notes
        -----
        - This method avoids copying the underlying DataFrame, reusing `flight.data`.
        - The `attrs` dictionary is shallow-copied; pass `attrs=flight.attrs`
          directly in the constructor if you require zero copies.
        """
        missing = [c for c in required_cols if c not in flight]
        if missing:
            raise KeyError(f"FlightWithEmissions missing required columns: {missing}")

        return cls(
            data=cast(pd.DataFrame, flight.data),
            attrs=dict(flight.attrs),
            required_cols=required_cols,
        )

    def has_columns(self, *cols: str) -> bool:
        """Quick check to see if additional columns are present."""
        return all(c in self for c in cols)

# ---- single protocol for all emission models ----
class EmissionModel(Protocol):
    """Callable that turns a Flight into a validated FlightWithEmissions."""
    def __call__(self, flight: Flight) -> FlightWithEmissions: ...


# ---- PyContrails Emissions wrapper ----
@dataclass(frozen=True)
class PyContrailsEmissionParams:
    """
    Parameters forwarded to pycontrails.models.emissions.Emissions.

    Keep this empty or add explicit fields you rely on; alternatively,
    pass arbitrary kwargs via `extra_kwargs` if you want full flexibility.
    """
    # Example (uncomment/add when you know the options you want to expose):
    # nvpm_model: str = "SCOPE11"
    # use_fuel_flow: bool = True
    extra_kwargs: Optional[Dict[str, Any]] = None

    

class PyContrailsEmissionModel:
    """
    Thin wrapper around pycontrails.models.emissions.Emissions that guarantees
    specific emission columns exist on the returned Flight.
    """

    def __init__(
        self,
        required_cols: tuple[str, ...] = DEFAULT_REQUIRED_EMISSION_COLS,
        params: PyContrailsEmissionParams | None = None,
        **emissions_kwargs: Any,  # convenience: forward directly to Emissions(...)
    ) -> None:
        self.required_cols = required_cols
        # Merge explicit params.extra_kwargs (if provided) with direct **emissions_kwargs
        extra = (params.extra_kwargs if (params and params.extra_kwargs) else {})  # type: ignore[arg-type]
        merged_kwargs = {**extra, **emissions_kwargs}
        self.em = Emissions(**merged_kwargs)

    def __call__(self, flight: Flight) -> FlightWithEmissions:
        # Emissions.eval attaches emission columns to the provided Flight
        out = self.em.eval(source=flight)
        # Validate and return a zero-copy wrapper
        return FlightWithEmissions.from_flight(out, required_cols=self.required_cols)


# ---- Eurocontrol model placeholder ----
class EurocontrolEmissionModel:
    """
    Placeholder for an alternative emissions implementation.
    When implemented, ensure it adds the required columns to `flight`,
    then return a validated wrapper.
    """

    def __init__(self, required_cols: tuple[str, ...] = DEFAULT_REQUIRED_EMISSION_COLS) -> None:
        self.required_cols = required_cols

    def __call__(self, flight: Flight) -> FlightWithEmissions:
        # TODO: compute and attach columns to `flight` (vectorized).
        # e.g., flight["nvpm_ei_m"] = ...
        # return FlightWithEmissions.from_flight(flight, required_cols=self.required_cols)
        raise NotImplementedError("Eurocontrol Emission Model not yet implemented")

# ---- DLR model placeholder ----
class DLREmissionModel:
    """
    Placeholder for an alternative emissions implementation.
    When implemented, ensure it adds the required columns to `flight`,
    then return a validated wrapper.
    """

    def __init__(self, required_cols: tuple[str, ...] = DEFAULT_REQUIRED_EMISSION_COLS) -> None:
        self.required_cols = required_cols

    def __call__(self, flight: Flight) -> FlightWithEmissions:
        # TODO: compute and attach columns to `flight` (vectorized).
        # e.g., flight["nvpm_ei_m"] = ...
        # return FlightWithEmissions.from_flight(flight, required_cols=self.required_cols)
        raise NotImplementedError("Eurocontrol Emission Model not yet implemented")


# ---- factory ----
class EmissionModelType(Enum):
    """Enum mapping model names to classes; safe factory that forwards params when supported."""
    PYCONTRAILS = PyContrailsEmissionModel
    EUROCONTROL = EurocontrolEmissionModel
    DLR = DLREmissionModel

    def get(self, *args: Any, **kwargs: Any) -> EmissionModel:
        cls = self.value
        sig = inspect.signature(cls)
        try:
            sig.bind_partial(*args, **kwargs)
            return cls(*args, **kwargs)  # type: ignore[call-arg]
        except TypeError:
            return cls()  # constructor takes no params
