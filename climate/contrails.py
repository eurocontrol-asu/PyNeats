# contrails.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Mapping, Protocol, cast

import pandas as pd
from pycontrails import Flight
from pycontrails.core.met import MetDataset
from pycontrails.models.cocip import Cocip

__all__ = [
    "DEFAULT_REQUIRED_CONTRAIL_COLS",
    "FlightWithContrailsImpact",
    "ContrailsModel",
    "ContrailsParams",
    "COCIPModel",
    "ContrailsModelType",
    "ContrailsStepError",
]

logger = logging.getLogger(__name__)

# ---- configuration -------------------------------------------------
# Keep minimal; expand as you standardize schema (e.g., "ci", "tau_cirrus", etc.)
DEFAULT_REQUIRED_CONTRAIL_COLS: Final[tuple[str, ...]] = ("ef",)  # effective radiative forcing (W/m^2)


# ---- error type ----------------------------------------------------
class ContrailsStepError(RuntimeError):
    """Raised when contrail impact evaluation fails or yields invalid output."""


# ---- validated flight view (zero-copy) -----------------------------
class FlightWithContrailsImpact(Flight):
    """
    Zero-copy view of a Flight guaranteed to contain contrail impact columns (e.g., 'ef').
    """

    def __init__(self, data: pd.DataFrame, attrs: dict[str, Any] | None = None) -> None:
        super().__init__(data=data, attrs=attrs)

    @classmethod
    def from_flight(
        cls,
        flight: Flight,
        required_cols: tuple[str, ...] = DEFAULT_REQUIRED_CONTRAIL_COLS,
    ) -> "FlightWithContrailsImpact":
        missing = [c for c in required_cols if c not in flight]
        if missing:
            raise KeyError(f"FlightWithContrailsImpact missing required columns: {missing}")
        return cls(
            data=cast(pd.DataFrame, flight.data),
            attrs=getattr(flight, "attrs", None),
        )

    def has_columns(self, *cols: str) -> bool:
        return all(c in self for c in cols)


# ---- protocol: return a base Flight for composability --------------
class ContrailsModel(Protocol):
    """
    A contrails step that enriches a Flight with contrail impact columns.
    Returns a base Flight; validate with FlightWithContrailsImpact at boundaries.
    """
    def __call__(self, flight: Flight) -> Flight: ...


# ---- params --------------------------------------------------------
@dataclass(frozen=True)
class ContrailsParams:
    """
    Parameters and datasets required by COCIP-like models.
    """
    met: MetDataset
    rad: MetDataset
    cocip_kwargs: Mapping[str, Any] = None  # forwarded to Cocip(...)

    def __post_init__(self) -> None:  # type: ignore[override]
        # dataclasses with frozen=True don't run __post_init__ for mutation; we just ensure defaults are dict-like at use time
        pass


# ---- PyContrails COCIP wrapper ------------------------------------
class COCIPModel:
    """
    Thin wrapper around `pycontrails.models.cocip.Cocip`.

    - Builds Cocip with provided met/rad and kwargs.
    - Calls `.eval(source=flight)` to attach contrail columns.
    - Validates required columns (fail fast) and returns the base Flight.
    """

    def __init__(
        self,
        params: ContrailsParams,
        required_cols: tuple[str, ...] = DEFAULT_REQUIRED_CONTRAIL_COLS,
        interpolation_use_indices: bool = True,
        **extra_kwargs: Any,
    ) -> None:
        self.required_cols = required_cols
        # Merge user-provided cocip kwargs with any extra kwargs here (extra wins)
        base_kwargs = dict(params.cocip_kwargs or {})
        base_kwargs.update(extra_kwargs)

        try:
            self._impl = Cocip(
                met=params.met,
                rad=params.rad,
                params=base_kwargs,
                interpolation_use_indices=interpolation_use_indices,
            )
        except Exception as e:
            logger.exception("Failed to initialize COCIP model")
            raise ContrailsStepError(f"COCIP initialization failed: {e}") from e

    def __call__(self, flight: Flight) -> Flight:
        try:
            out: Flight = self._impl.eval(source=flight)
        except Exception as e:
            logger.exception("COCIP backend evaluation failed")
            raise ContrailsStepError(f"COCIP evaluation failed: {e}") from e

        # Validate presence of required columns (zero-copy)
        try:
            _ = FlightWithContrailsImpact.from_flight(out, required_cols=self.required_cols)
        except KeyError as e:
            logger.error("COCIP output missing required columns: %s", e)
            raise ContrailsStepError(f"COCIP output missing required columns: {e}") from e

        logger.info("COCIP step completed successfully")
        return out


# ---- factory -------------------------------------------------------
class ContrailsModelType(Enum):
    """Enum factory for contrails models."""
    COCIP = COCIPModel

    def get(self, *args: Any, **kwargs: Any) -> ContrailsModel:
        impl = self.value  # type: ignore[assignment]
        return impl(*args, **kwargs)  # type: ignore[misc]
