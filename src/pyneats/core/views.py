# core/views.py
from __future__ import annotations

from typing import ClassVar, Iterable, cast, TypeVar
from pycontrails import Flight

from .steps import StepError  # reuse your common error base

__all__ = [
    "ValidationError",
    "FlightView",
]

class ValidationError(StepError):
    """Raised when a validated Flight view cannot guarantee its schema."""

TView = TypeVar("TView", bound="FlightView")

class FlightView(Flight):
    """
    Zero-copy, typed *view* over a Flight with declarative column requirements.

    - Subclasses declare REQUIRED/OPTIONAL.
    - `from_flight()` validates and returns a *casted* view (no DataFrame copy).
    """

    REQUIRED: ClassVar[tuple[str, ...]] = ()
    OPTIONAL: ClassVar[tuple[str, ...]] = ()

    # ---- Validation / construction -------------------------------------------------

    @classmethod
    def from_flight(
        cls: type[TView],
        flight: Flight,
        *,
        require: Iterable[str] | None = None,
    ) -> TView:
        """
        Validate `flight` has all required columns and return a typed, zero-copy view.

        Parameters
        ----------
        flight : Flight
            Source flight. Its `.data` and `.attrs` are reused (no copy).
        require : iterable[str], optional
            Extra columns required *in addition* to `cls.REQUIRED`.

        Raises
        ------
        ValidationError
            If any required column is missing.
        """
        required = tuple(cls.REQUIRED) + (tuple(require) if require else ())
        missing = [c for c in required if c not in flight]
        if missing:
            raise ValidationError(cls.__name__, f"missing columns: {missing}")
        # Zero-copy: same underlying data/attrs; only the *type* changes.
        return cast(TView, flight)

    # ---- Convenience helpers -------------------------------------------------------

    def has(self, *cols: str) -> bool:
        return all(c in self for c in cols)

    def ensure(self, *cols: str) -> None:
        missing = [c for c in cols if c not in self]
        if missing:
            raise ValidationError(type(self).__name__, f"missing columns: {missing}")
