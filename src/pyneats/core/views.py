# core/views.py
from __future__ import annotations
from typing import ClassVar, Iterable, TypeVar, cast
from pycontrails import Flight

from .steps import StepError

__all__ = ["ValidationError", "FlightView"]

class ValidationError(StepError):
    """Raised when a validated Flight view cannot guarantee its schema."""

TView = TypeVar("TView", bound="FlightView")

class FlightView(Flight):
    """Zero-copy, typed *view* over a Flight with declarative column requirements."""

    REQUIRED: ClassVar[tuple[str, ...]] = ()
    OPTIONAL: ClassVar[tuple[str, ...]] = ()

    # --- helpers ------------------------------------------------------

    @classmethod
    def _all_required(cls, extra: Iterable[str] | None = None) -> tuple[str, ...]:
        # Merge REQUIRED across the whole MRO (parents first), dedup while preserving order
        seen: set[str] = set()
        out: list[str] = []
        for base in reversed(cls.__mro__):  # parents first
            req = getattr(base, "REQUIRED", ())
            for c in req:
                if c not in seen:
                    seen.add(c)
                    out.append(c)
        if extra:
            for c in extra:
                if c not in seen:
                    seen.add(c)
                    out.append(c)
        return tuple(out)

    @classmethod
    def _all_optional(cls) -> tuple[str, ...]:
        seen: set[str] = set()
        out: list[str] = []
        for base in reversed(cls.__mro__):
            opt = getattr(base, "OPTIONAL", ())
            for c in opt:
                if c not in seen:
                    seen.add(c)
                    out.append(c)
        return tuple(out)

    # --- construction / validation -----------------------------------

    @classmethod
    def from_flight(
        cls: type[TView],
        flight: Flight,
        *,
        require: Iterable[str] | None = None,
    ) -> TView:
        required = cls._all_required(require)
        missing = [c for c in required if c not in flight]
        if missing:
            raise ValidationError(cls.__name__, f"missing columns: {missing}")
        # Zero-copy: we only *narrow the type* for the caller
        return cast(TView, flight)

    # --- convenience --------------------------------------------------

    def has(self, *cols: str) -> bool:
        return all(c in self for c in cols)

    def ensure(self, *cols: str) -> None:
        missing = [c for c in cols if c not in self]
        if missing:
            raise ValidationError(type(self).__name__, f"missing columns: {missing}")

    @classmethod
    def matches(cls, flight: Flight) -> bool:
        """Runtime check (non-typing) that the flight satisfies this view."""
        return all(c in flight for c in cls._all_required())

