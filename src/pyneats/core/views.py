from __future__ import annotations

from typing import ClassVar, Iterable, TypeVar, Tuple, cast, Any
from pycontrails import Flight
from pycontrails.utils import json as json_utils
from pyneats.core.steps import StepError
import numpy as np
import warnings


__all__ = [
    "ValidationError",
    "FlightView",
]


class ValidationError(StepError):
    """Raised when a validated Flight view cannot guarantee its schema."""


TView = TypeVar("TView", bound="FlightView")


class FlightView(Flight):
    """Zero-copy, typed *view* over a Flight with declarative column requirements."""

    # Column requirements
    REQUIRED: ClassVar[Tuple[str, ...]] = ()
    OPTIONAL: ClassVar[Tuple[str, ...]] = ()

    # Attribute (Flight.attrs) requirements
    ATTRS_REQUIRED: ClassVar[Tuple[str, ...]] = ()
    ATTRS_OPTIONAL: ClassVar[Tuple[str, ...]] = ()

    # --- helpers ------------------------------------------------------

    @classmethod
    def _all_required(cls, extra: Iterable[str] | None = None) -> Tuple[str, ...]:
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

    @classmethod
    def _all_attrs_required(cls) -> Tuple[str, ...]:
        seen: set[str] = set()
        out: list[str] = []
        for base in reversed(cls.__mro__):
            req = getattr(base, "ATTRS_REQUIRED", ())
            for a in req:
                if a not in seen:
                    seen.add(a)
                    out.append(a)
        return tuple(out)

    @classmethod
    def _all_attrs_optional(cls) -> Tuple[str, ...]:
        seen: set[str] = set()
        out: list[str] = []
        for base in reversed(cls.__mro__):
            opt = getattr(base, "ATTRS_OPTIONAL", ())
            for a in opt:
                if a not in seen:
                    seen.add(a)
                    out.append(a)
        return tuple(out)

    # --- construction / validation -----------------------------------

    @classmethod
    def from_flight(
        cls: type[TView],
        flight: Flight,
        *,
        require: Iterable[str] | None = None,
    ) -> TView:
        required_cols = cls._all_required(require)
        required_attrs = cls._all_attrs_required()

        missing_cols = [c for c in required_cols if c not in flight]
        missing_attrs = [a for a in required_attrs if a not in flight.attrs]

        if missing_cols or missing_attrs:
            messages = []

            if missing_cols:
                messages.append(f"missing columns: {', '.join(missing_cols)}")

            if missing_attrs:
                messages.append(f"missing attrs: {', '.join(missing_attrs)}")

            raise ValidationError(cls.__name__, "; ".join(messages))

        # Zero-copy: we only *narrow the type* for the caller
        return cast(TView, flight)

    # --- convenience --------------------------------------------------

    def has(self, *cols: str) -> bool:
        return all(c in self for c in cols)

    def ensure(self, *cols: str) -> None:
        missing = [c for c in cols if c not in self]
        if missing:
            raise ValidationError(type(self).__name__, f"missing columns: {missing}")

    def has_attrs(self, *attrs: str) -> bool:
        return all(a in self.attrs for a in attrs)

    def ensure_attrs(self, *attrs: str) -> None:
        missing = [a for a in attrs if a not in self.attrs]
        if missing:
            raise ValidationError(type(self).__name__, f"missing attrs: {missing}")

    @classmethod
    def matches(cls, flight: Flight) -> bool:
        """Runtime check (non-typing) that the flight satisfies this view."""
        cols_ok = all(c in flight for c in cls._all_required())
        attrs_ok = all(a in flight.attrs for a in cls._all_attrs_required())
        return cols_ok and attrs_ok

    # Overload method
    def to_dict(self) -> dict[str, Any]:
        np_encoder = json_utils.NumpyEncoder()

        def encode(key: str, obj: Any) -> Any:
            # Try to handle some pandas objects
            if hasattr(obj, "to_numpy"):
                obj = obj.to_numpy()

            # Convert numpy objects to python objects
            if isinstance(obj, np.ndarray | np.generic):
                # round time to unix seconds
                if key == "time":
                    return np_encoder.default(obj.astype("datetime64[s]").astype(int))

                # round specific keys in precision
                return np_encoder.default(obj)

            # Pass through everything else
            return obj

        data = {k: encode(k, v) for k, v in self.data.items()}
        attrs = {k: encode(k, v) for k, v in self.attrs.items()}

        # Issue warning if any keys are duplicated
        common_keys = data.keys() & attrs.keys()
        if common_keys:
            warnings.warn(
                f"Found duplicate keys in data and attrs: {common_keys}. "
                "Data keys will overwrite attrs keys in returned dictionary."
            )

        return {**attrs, **data}
