from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Generic, Protocol, TypeVar, runtime_checkable
import logging

from pycontrails import Flight

__all__ = [
    "InFlight",
    "OutFlight",
    "StepError",
    "Step",
    "BaseStep",
]

# --- Variance-aware type variables for pipeline steps ---
InFlight = TypeVar("InFlight", bound=Flight, contravariant=True)
OutFlight = TypeVar("OutFlight", bound=Flight, covariant=True)


# --- Common step error base ---
class StepError(RuntimeError):
    """Base class for domain errors raised by steps."""
    def __init__(self, step: str, msg: str):
        super().__init__(f"{step}: {msg}")
        self.step = step


# --- Structural contract: any callable (InFlight) -> OutFlight qualifies as a Step ---
@runtime_checkable
class Step(Protocol[InFlight, OutFlight]):
    def __call__(self, flight: InFlight) -> OutFlight: ...
    

# --- Convenience base with timing, logging, and error policy ---
@dataclass
class BaseStep(Generic[InFlight, OutFlight]):
    """
    Uniform wrapper: timing, structured logging, and predictable error handling.
    Subclasses must implement `run()`.
    """
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__))

    @classmethod
    def name(cls) -> str:
        return cls.__name__

    # Subclasses implement: core logic without cross-cutting concerns
    def run(self, flight: InFlight) -> OutFlight:  # pragma: no cover
        raise NotImplementedError

    # Public callable interface (satisfies Step protocol)
    def __call__(self, flight: InFlight) -> OutFlight:
        t0 = perf_counter()
        try:
            out = self.run(flight)
        except StepError:
            # Domain errors already carry context; don’t double-wrap.
            self.logger.error("%s failed", self.name(), exc_info=True, extra={"step": self.name()})
            raise
        except Exception as e:
            # Unexpected -> normalize into a StepError with context chain
            self.logger.exception("Unexpected %s error", self.name(), extra={"step": self.name()})
            raise StepError(self.name(), f"unexpected: {e}") from e

        dt = perf_counter() - t0
        # Use structured logging fields so runners can aggregate timings
        self.logger.info("%s ok", self.name(), extra={"step": self.name(), "dt": dt})
        return out
