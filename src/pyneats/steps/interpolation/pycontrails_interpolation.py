"""
PyContrails Trajectory Interpolation Module

Implements trajectory interpolation using pycontrails' resample_and_fill method.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pycontrails import Flight

from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.core.views import ValidationError
from pyneats.steps.interpolation.params import TrajectoryInterpolationParams
from pyneats.steps.interpolation.protocol import TrajectoryInterpolationStepError
from pyneats.steps.interpolation.protocol import TrajectoryInterpolator
from pyneats.steps.parsing.views import Flight4D


__all__ = [
    "PyContrailsInterpolationParams",
    "PyContrailsInterpolator",
]


@dataclass(frozen=True)
class PyContrailsInterpolationParams(TrajectoryInterpolationParams):
    """
    Parameters for trajectory interpolation/resampling using pycontrails.
    """


@register(TrajectoryInterpolator, "pycontrails")  # type: ignore[type-abstract]
class PyContrailsInterpolator(
    BaseStep[
        Flight4D,
        Flight4D,
        PyContrailsInterpolationParams,
    ]
):
    """
    Interpolates flight trajectory data using pycontrails.

    This class provides trajectory interpolation functionality. It handles:
    - Resampling of mandatory flight parameters (wrapping pycontrails' resample_and_fill)
    - Linear interpolation of optional columns
    - Input/output validation
    - Error handling

    Parameters
    ----------
    flight : Flight4D
        Input flight trajectory data (validated upstream).

    Returns
    -------
    Flight4D
        Interpolated and validated flight trajectory (zero-copy).

    Raises
    ------
    TrajectoryInterpolationStepError
        If interpolation or validation fails.
    """

    default_params = PyContrailsInterpolationParams

    def run(self, flight: Flight4D) -> Flight4D:
        """
        Interpolate a flight trajectory using pycontrails and linear interpolation for optional columns.

        Parameters
        ----------
        flight : Flight4D
            Input flight trajectory data.

        Returns
        -------
        Flight4D
            Interpolated and validated flight trajectory.

        Raises
        ------
        TrajectoryInterpolationStepError
            If interpolation or validation fails.
        """
        try:
            # Keep original dataframe for interpolation of optional columns
            original = flight.dataframe

            # Perform pycontrails interpolation
            interpolated_flight: Flight = flight.resample_and_fill(
                self.params.interpolation_time
            )

            if len(interpolated_flight) < 2:
                raise TrajectoryInterpolationStepError(
                    "resample_and_fill resulted in a trajectory with less than 2 waypoints"
                )

            # Interpolate optional columns
            t_orig_num = original["time"].values.astype(np.int64)
            t_new_num = interpolated_flight["time"].astype(np.int64)

            for col in Flight4D.OPTIONAL:
                if col in original.columns:
                    y_orig = original[col].astype(float)
                    interpolated_values = np.interp(t_new_num, t_orig_num, y_orig)
                    interpolated_flight[col] = interpolated_values

        except Exception as e:
            raise TrajectoryInterpolationStepError(
                f"resample_and_fill failed: {e}"
            ) from e

        try:
            return Flight4D.from_flight(
                interpolated_flight
            )  # schema/type validation (zero-copy)
        except ValidationError as ve:
            raise TrajectoryInterpolationStepError(
                f"invalid resampled schema: {ve}"
            ) from ve
