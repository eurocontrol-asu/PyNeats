from __future__ import annotations

from dataclasses import dataclass, asdict
from dacite import from_dict
from time import perf_counter
from typing import Generic, Protocol, TypeVar, runtime_checkable, Type, Any
import logging
import pandas as pd

from pycontrails import Flight

__all__ = [
    "InFlight",
    "OutFlight",
    "Params",
    "StepError",
    "Step",
    "BaseStep",
    "BaseParams",
]


@dataclass(frozen=True)
class BaseParams:
    """Base class for step parameters."""

    pass


# --- Variance-aware type variables for pipeline steps ---
InFlight = TypeVar("InFlight", Flight, pd.DataFrame, contravariant=True)
OutFlight = TypeVar("OutFlight", bound=Flight, covariant=True)
Params = TypeVar("Params", bound=BaseParams)


# --- Common step error base ---
class StepError(RuntimeError):
    """Base class for domain errors raised by steps."""


# --- Structural contract: any callable (InFlight) -> OutFlight qualifies as a Step ---
@runtime_checkable
class Step(Protocol[InFlight, OutFlight]):
    def __call__(self, flight: InFlight) -> OutFlight: ...


def update_param_dict(
    param_dict: dict[str, Any],
    new_params: dict[str, Any],
) -> None:
    for param, value in new_params.items():
        try:
            old_value = param_dict[param]
        except KeyError:
            msg = (
                f"Unknown parameter '{param}' passed into model. Possible "
                f"parameters include {', '.join(param_dict)}."
            )
            raise KeyError(msg) from None

        param_dict[param] = value


# --- Convenience base with timing, logging, and error policy ---
class BaseStep(Generic[InFlight, OutFlight, Params]):
    """
    Uniform wrapper: timing, structured logging, and predictable error handling.
    Subclasses must implement `run()` and define `default_params`.
    """

    # Subclasses must define a concrete dataclass type
    default_params: Type[Params]

    def _load_params(
        self,
        params: Params | dict | None = None,
        **params_kwargs,
    ):
        if params is None:
            params_dict = asdict(self.default_params())
        elif isinstance(params, self.default_params):
            params_dict = asdict(params)
        elif isinstance(params, dict):
            params_dict = asdict(self.default_params())
            update_param_dict(params_dict, params)
        else:
            raise TypeError(
                f"Step parameters must be {self.default_params.__name__} or dict"
            )

        update_param_dict(params_dict, params_kwargs)
        self.params = from_dict(self.default_params, params_dict)

    def __init__(
        self,
        params: Params | dict | None = None,
        **params_kwargs: Any,
    ):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._load_params(params, **params_kwargs)
        self._post_init()  # subclass hook

    def _post_init(self) -> None:
        """Optional hook for subclasses to initialize additional attributes."""
        pass

    # Subclasses implement: core logic without cross-cutting concerns
    def run(self, flight: InFlight) -> OutFlight:  # pragma: no cover
        raise NotImplementedError

    # Public callable interface (satisfies Step protocol)
    def __call__(self, flight: InFlight) -> OutFlight:
        t0 = perf_counter()

        try:
            out = self.run(flight)
        except StepError:
            self.logger.error(
                "%s failed",
                self.__class__.__name__,
                exc_info=True,
                extra={"step": self.__class__.__name__},
            )
            raise
        except Exception as e:
            self.logger.exception(
                "Unexpected %s error",
                self.__class__.__name__,
                extra={"step": self.__class__.__name__},
            )
            raise StepError(f"unexpected: {e}") from e

        dt = perf_counter() - t0

        self.logger.info(
            "%s ok",
            self.__class__.__name__,
            extra={"step": self.__class__.__name__, "dt": dt},
        )

        return out
