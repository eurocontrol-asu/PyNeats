"""NEATS Processing Steps Core Module

This module provides the foundational architecture for all NEATS processing steps,
implementing a generic pipeline pattern with strong typing and error handling.

Key Components:
   - BaseParams: Foundation for step-specific parameter classes
   - BaseStep: Abstract base with logging, timing, and error handling
   - Step: Protocol defining the core interface
   - InFlight/OutFlight: Type variables for flight data I/O
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import asdict
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from typing import Generic
from typing import Protocol
from typing import TypeVar
from typing import runtime_checkable

import pandas as pd
from dacite import from_dict
from pycontrails import Flight


__all__ = [
    "InFlight",
    "OutFlight",
    "InFlightT",
    "OutFlightT",
    "Params",
    "StepError",
    "Step",
    "VectorizedStep",
    "BaseStep",
    "BaseParams",
]


@dataclass(frozen=True)
class BaseParams:
    """
    Base class for step parameters.

    This class should be subclassed to define parameters for each NEATS processing step.
    """

    pass


# --- Variance-aware type variables for pipeline steps ---
InFlight = TypeVar("InFlight", bound=Flight | pd.DataFrame, contravariant=True)
OutFlight = TypeVar("OutFlight", bound=Flight, covariant=True)
Params = TypeVar("Params", bound=BaseParams)


# --- Common step error base ---


class StepError(RuntimeError):
    """
    Base class for domain errors raised by steps.

    Raised when a NEATS processing step encounters an error.
    """


# --- Structural contract: any callable (InFlight) -> OutFlight qualifies as a Step ---
@runtime_checkable
class Step(Protocol[InFlight, OutFlight]):
    """
    Protocol defining the core interface for NEATS processing steps.

    Any callable that takes an input flight and returns an output flight qualifies as a Step.

    Methods
    -------
    __call__(flight: InFlight) -> OutFlight
        Execute the step on the given flight.
    """

    def __call__(self, flight: InFlight) -> OutFlight: ...


# Invariant type variables for VectorizedStep (lists are invariant)
InFlightT = TypeVar("InFlightT", bound=Flight)
OutFlightT = TypeVar("OutFlightT", bound=Flight)


@runtime_checkable
class VectorizedStep(Protocol[InFlightT, OutFlightT]):
    """
    Protocol for steps that support fleet-level vectorized execution.

    Steps implementing this protocol can process multiple flights in a single
    batch operation, enabling performance optimizations like vectorized
    computations and reduced overhead.

    Parameters
    ----------
    InFlightT : TypeVar
        The input flight type (invariant, bound to Flight).
    OutFlightT : TypeVar
        The output flight type (invariant, bound to Flight).

    Methods
    -------
    run_fleet(flights: list[InFlightT]) -> list[OutFlightT]
        Run the step on a list of flights.
    """

    def run_fleet(self, flights: list[InFlightT]) -> list[OutFlightT]: ...


def update_param_dict(
    param_dict: dict[str, Any],
    new_params: dict[str, Any],
) -> None:
    """
    Update a parameter dictionary with new values.

    Parameters
    ----------
    param_dict : dict of str to Any
        The original parameter dictionary to update.
    new_params : dict of str to Any
        New parameters to update in the dictionary.

    Raises
    ------
    KeyError
        If a parameter in new_params does not exist in param_dict.
    """
    for param, value in new_params.items():
        try:
            _ = param_dict[param]
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
    Uniform wrapper for NEATS steps: timing, structured logging, and predictable error handling.

    Subclasses must implement `run()` and define `default_params`.

    Attributes
    ----------
    default_params : type
        The dataclass type for step parameters.
    logger : logging.Logger
        Logger for the step.
    params : Params
        Parameters for the step.

    Methods
    -------
    run(flight: InFlight) -> OutFlight
        Core logic for the step (to be implemented by subclasses).
    __call__(flight: InFlight) -> OutFlight
        Public interface for running the step with logging and error handling.
    _load_params(params, **params_kwargs)
        Load and validate parameters.
    _post_init()
        Optional hook for subclass initialization.
    """

    # Subclasses must define a concrete dataclass type
    default_params: type[Params]

    def _load_params(
        self,
        params: Params | Mapping[str, Any] | None = None,
        **params_kwargs: Any,
    ) -> None:
        """
        Load and validate parameters for the step.

        Parameters
        ----------
        params : Params or Mapping[str, Any] or None, optional
            Parameters to load. If None, use defaults.
        **params_kwargs : Any
            Additional parameters to override.

        Raises
        ------
        TypeError
            If parameters are not of the correct type.
        """
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
        params: Params | Mapping[str, Any] | None = None,
        **params_kwargs: Any,
    ):
        """
        Initialize the BaseStep.

        Parameters
        ----------
        params : Params or Mapping[str, Any] or None, optional
            Parameters to load. If None, use defaults.
        **params_kwargs : Any
            Additional parameters to override.
        """
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self._load_params(params, **params_kwargs)
        self._post_init()  # subclass hook

    def _post_init(self) -> None:
        """
        Optional hook for subclasses to initialize additional attributes.

        Subclasses can override this method to perform additional initialization.
        """
        pass

    def run(self, flight: InFlight) -> OutFlight:  # pragma: no cover
        """
        Core logic for the step (to be implemented by subclasses).

        Parameters
        ----------
        flight : InFlight
            The input flight data.

        Returns
        -------
        OutFlight
            The output flight data.

        Raises
        ------
        NotImplementedError
            If not implemented in subclass.
        """
        raise NotImplementedError

    # Public callable interface (satisfies Step protocol)
    def __call__(self, flight: InFlight) -> OutFlight:
        """
        Run the step with timing, logging, and error handling.

        Parameters
        ----------
        flight : InFlight
            The input flight data.

        Returns
        -------
        OutFlight
            The output flight data.

        Raises
        ------
        StepError
            If a domain-specific error occurs.
        """
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
