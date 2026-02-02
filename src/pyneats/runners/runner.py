from abc import ABC, abstractmethod
from typing import Self
import logging

logger = logging.getLogger(__name__)

class Runner(ABC):
    """
    Abstract base class the defines the backbone structure for both flight and fleet computations pipeline

    It orchestrates the sequential processing of flight data through multiple computational components:

    - Flight parsing (NM/ADS-B data)
    - Trajectory interpolation
    - Weather data intersection
    - Aircraft performance computation
    - Emissions calculation
    - Contrail effects and Other Non-CO2 effects assessment
    - Non CO2 equivalent computation
        
    Subclasses must implement the individual data processing steps.
    The `eval` method provides the standardized template for the execution flow.
    """

    def eval(self) -> Self:
        """
        Run the full pipeline with optional early termination.

        If a subclass sets `_pipeline_aborted = True` (e.g., when all items fail
        at a step), the pipeline will stop early and proceed to `_extract_results()`.
        Subclasses that don't define `_pipeline_aborted` get the original behavior.
        """
        logger.info(f"{self.__class__.__name__}: starting pipeline")

        steps = [
            self._load_data,
            self._parse_flight,
            self._interpolate,
            self._intersect_weather,
            self._performance,
            self._emissions,
            self._climate_impact,
            self._climate_metrics,
        ]

        for step in steps:
            step()
            if getattr(self, '_pipeline_aborted', False):
                logger.warning(
                    "Pipeline aborted after %s - all flights failed",
                    step.__name__,
                )
                break

        return self._extract_results()

    @abstractmethod
    def _load_data(self) -> Self:
        """Load raw flight data."""

    @abstractmethod
    def _parse_flight(self) -> Self:
        """Parse raw data into flight objects."""

    @abstractmethod
    def _interpolate(self) -> Self:
        """Fill gaps in trajectory data."""

    @abstractmethod
    def _intersect_weather(self) -> Self:
        """Combine flight paths with meteorological data."""

    @abstractmethod
    def _performance(self) -> Self:
        """Calculate aircraft performance metrics."""

    @abstractmethod
    def _emissions(self) -> Self:
        """Calculate engine emissions."""

    @abstractmethod
    def _climate_impact(self) -> Self:
        """Assess environmental impact (e.g., radiative forcing)."""

    @abstractmethod
    def _climate_metrics(self) -> Self:
        """Generate final climate-related statistical metrics."""

    @abstractmethod
    def _extract_results(self) -> Self:
        """Format and return the final output data."""