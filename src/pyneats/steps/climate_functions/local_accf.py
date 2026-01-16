"""Local Implementation of Algorithmic Climate Change Functions (ACCF)

This module provides a local implementation of the ACCF approach for computing non-CO2
climate impacts of aviation outside of contrails impacts.
It calculates temperature responses in K at 20 years horizon for three key species:

   - Ozone (O3) formation from NOx emissions
   - Methane (CH4) depletion from NOx emissions
   - Water vapor (H2O) direct effects

The use of a local implementation allows for a more efficient computation
avoiding heavy weather data transfers and overheads between PyContrails and ClimaCCF
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping

import numpy as np
from numpy.typing import NDArray
import pandas as pd

from pycontrails import Flight
from pyneats.core.steps import BaseStep
from pyneats.core.neats_default_parameters import DEFAULT_ACCF_VALIDITY_PRESSURE
from pyneats.core.steps_registry import register
from pyneats.steps.emissions.views import FlightWithEmissions
from pyneats.steps.climate_functions.views import FlightWithNonCO2Impact
from pyneats.steps.climate_functions.protocol import NonCO2Model, ClimateStepError
from pyneats.steps.climate_functions.climaccf import aCCFParams

from pyneats.core.physics import (
    ACCF_SCALE_03,
    ACCF_SCALE_CH4,
    ACCF_SCALE_H2O,
    SOLAR_CONSTANT,
)


__all__ = ["LocalACCFParams", "LocalACCFModel"]

# ----------------------------- Params -------------------------------- #


@dataclass(frozen=True)
class LocalACCFParams(aCCFParams):
    """Parameters for the Local Algorithmic Climate Change Functions (ACCF) model."""

    col_air_temperature: str = "air_temperature"  # [K]
    col_geopotential: str = "geopotential"  # [m^2 s^-2]
    col_time: str = "time"  # datetime64
    col_latitude: str = "latitude"  # [deg]
    col_potential_vorticity: str = "potential_vorticity"
    col_nox_ei: str = "nox_ei"  # [kg(NOx)/kg(fuel)]
    col_fuel_burn: str = "fuel_burn"  # [kg(fuel)]
    col_air_pressure: str = "air_pressure"
    col_phase: str = "phase"

    scale_o3: Mapping[str, float] = field(default_factory=lambda: ACCF_SCALE_03)
    scale_ch4: Mapping[str, float] = field(
        default_factory=lambda: ACCF_SCALE_CH4,
    )
    scale_h2o: Mapping[str, float] = field(
        default_factory=lambda: ACCF_SCALE_H2O,
    )
    solar_constant: float = SOLAR_CONSTANT

    def __post_init__(self) -> None:
        if self.accf_kwargs["accf_v"] not in self.scale_o3:
            raise ClimateStepError(
                f"Unknown ACCF version '{self.accf_kwargs['accf_v']}' for O3 scaling."
            )
        if self.accf_kwargs["accf_v"] not in self.scale_ch4:
            raise ClimateStepError(
                f"Unknown ACCF version '{self.accf_kwargs['accf_v']}' for CH4 scaling."
            )
        if self.accf_kwargs["accf_v"] not in self.scale_h2o:
            raise ClimateStepError(
                f"Unknown ACCF version '{self.accf_kwargs['accf_v']}' for H2O scaling."
            )


# --------------------------- Utilities -------------------------------- #

FloatArray = NDArray[np.float64]


def _as_np(series: pd.Series | FloatArray) -> FloatArray:
    """Convert a pandas Series or array to float64 NumPy array (preserve NaNs)."""
    return np.asarray(series, dtype=np.float64)


def _fin_rowwise(
    time_series: pd.Series | NDArray[np.datetime64],
    lat_series: pd.Series | FloatArray,
    solar_constant: float,
) -> FloatArray:
    """Top-of-atmosphere incoming shortwave parametrization."""
    times = np.asarray(pd.to_datetime(time_series), dtype="datetime64[ns]")
    doy = (times.astype("datetime64[D]") - times.astype("datetime64[Y]")).astype(
        "timedelta64[D]"
    ).astype(int) + 1
    delta = np.deg2rad(-23.44 * np.cos(2.0 * np.pi / 365.0 * (doy + 10)))
    phi = np.deg2rad(np.asarray(lat_series, dtype=np.float64))
    theta = np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta)
    return (solar_constant * theta).astype(np.float64)


# ----------------------------- Model ---------------------------------- #


@register(NonCO2Model, "local_accf")  #  replaces the ClimAccf backend
class LocalACCFModel(
    BaseStep[
        FlightWithEmissions,
        FlightWithNonCO2Impact,
        LocalACCFParams,
    ]
):
    """Local implementation of Algorithmic Climate Change Functions (ACCF).

    This model computes non-CO2 climate impacts for aircraft emissions using the ACCF
    simple surrogate approach. It calculates impacts for:
    - Ozone (O3) formation
    - Methane (CH4) depletion
    - Water vapor (H2O) effects

    The implementation uses local meteorological conditions already interpolated on the flight
    using PyContrails utilities

    Key Features:
        - Species-specific formulations based on meteorological parameters
        - Version-specific scaling factors
        - PMO multiplier option for CH4
    """

    default_params = LocalACCFParams

    # ---- plumbing ----
    def _require_cols(self, flight: Flight, cols: list[str]) -> None:
        columns = list(flight.data.keys())
        missing = [c for c in cols if c not in columns]
        if missing:
            raise ClimateStepError(f"Missing required flight columns: {missing}")

    # ---- O3: raw formula & compute ----
    @staticmethod
    def o3_raw_formula(t: FloatArray, gp: FloatArray) -> FloatArray:
        """Returns raw (unscaled, unclamped) P-ATR20-O3 [K/kg(NOx)]."""

        return -5.20e-11 + 2.30e-13 * t + 4.85e-16 * gp - 2.04e-18 * t * gp

    def compute_o3(self, flight: Flight) -> FloatArray:
        """Compute ozone (O3) Pulse-based Average Temperature Response over 20 years (P-ATR20)
        for ozone formation from NOx emissions.
        Uses air temperature and geopotential as input parameters

        """

        t = _as_np(flight[self.params.col_air_temperature])
        gp = _as_np(flight[self.params.col_geopotential])

        accf = self.o3_raw_formula(t, gp)
        accf = np.where(
            np.isfinite(accf), np.maximum(accf, 0.0), np.nan
        )  # clamp negatives to 0
        try:
            # Scaling with version-specific factor
            accf /= self.params.scale_o3[self.params.accf_kwargs["accf_v"]]

            # convert from K-per-kg(NOx) to K-per-kg(fuel) with NOx EI
            accf *= _as_np(flight[self.params.col_nox_ei])

            # Final conversion from K-per-kg(fuel) to K
            accf *= _as_np(flight[self.params.col_fuel_burn])

        except KeyError as e:
            raise ClimateStepError(
                f"Unknown ACCF version for O3: {self.params.accf_kwargs['accf_v']}"
            ) from e

        return accf

    # ---- CH4: raw formula & compute ----
    @staticmethod
    def ch4_raw_formula(gp: FloatArray, fin: FloatArray) -> FloatArray:
        """Returns raw (unscaled, unclamped) P-ATR20-CH4 [K/kg(NOx)]."""

        return -9.83e-13 + 1.99e-18 * gp - 6.32e-16 * fin + 6.12e-21 * gp * fin

    def compute_ch4(self, flight: Flight) -> FloatArray:
        """Compute methane (CH4) Pulse-based Average Temperature Response over 20 years (P-ATR20)
        for methane depletion from NOx emissions.
        Uses geopotential and top-of-atmosphere incoming shortwave radiation as input parameters.
        """

        gp = _as_np(flight[self.params.col_geopotential])
        fin = _fin_rowwise(
            flight[self.params.col_time],
            flight[self.params.col_latitude],
            self.params.solar_constant,
        )

        accf = self.ch4_raw_formula(gp, fin)
        accf = np.where(
            np.isfinite(accf), np.minimum(accf, 0.0), np.nan
        )  # clamp positives to 0
        try:
            # Scaling with version-specific factor
            accf /= self.params.scale_ch4[self.params.accf_kwargs["accf_v"]]

            # convert from K-per-kg(NOx) to K-per-kg(fuel) with NOx EI
            accf *= _as_np(flight[self.params.col_nox_ei])

            # Final conversion from K-per-kg(fuel) to K
            accf *= _as_np(flight[self.params.col_fuel_burn])

        except KeyError as e:
            raise ClimateStepError(
                f"Unknown ACCF version for CH4: {self.params.accf_kwargs['accf_v']}"
            ) from e
        if self.params.accf_kwargs["PMO"]:
            accf = accf * 1.29

        return accf

    # ---- H2O: raw formula & compute ----
    @staticmethod
    def h2o_raw_formula(pv: FloatArray) -> FloatArray:
        """Returns raw (unscaled) P-ATR20-H2O [K/kg(fuel)]."""

        return 4.05e-16 + 1.48e-16 * np.abs(pv)

    def compute_h2o(self, flight: Flight) -> FloatArray:
        """Compute water vapor (H2O) Pulse-based Average Temperature Response over 20 years (P-ATR20)
        for water vapor emissions.
        Uses potential vorticity as input parameter.
        """

        pv = _as_np(flight[self.params.col_potential_vorticity])
        accf = self.h2o_raw_formula(pv)
        try:
            # Scaling with version-specific factor
            accf /= self.params.scale_h2o[self.params.accf_kwargs["accf_v"]]

            # Final conversion from K-per-kg(fuel) to K
            accf *= _as_np(flight[self.params.col_fuel_burn])

        except KeyError as e:
            raise ClimateStepError(
                f"Unknown ACCF version for H2O: {self.params.accf_kwargs['accf_v']}"
            ) from e

        return accf

    # ---- pipeline entrypoint ----
    def run(self, flight: FlightWithEmissions) -> FlightWithNonCO2Impact:
        self._require_cols(
            flight,
            [
                self.params.col_air_temperature,
                self.params.col_geopotential,
                self.params.col_time,
                self.params.col_latitude,
                self.params.col_potential_vorticity,
            ],
        )

        o3 = self.compute_o3(flight)
        ch4 = self.compute_ch4(flight)
        h2o = self.compute_h2o(flight)

        # Discounting output values from the regression functions on part of the flight
        # that are outside the validity region of aCCFs formulas
        # Create the mask for INVALID rows

        # Condition 1: Pressure is too high (Altitude too low)
        bad_pressure = (
            flight[self.params.col_air_pressure] > DEFAULT_ACCF_VALIDITY_PRESSURE
        )

        # Condition 2: Phase is not Cruise
        # bad_phase = flight[self.params.col_phase] != "Cruise"

        mask = bad_pressure

        o3[mask] = 0.0
        ch4[mask] = 0.0
        h2o[mask] = 0.0

        # Write directly on the flight
        flight["ATR_20_O3"] = o3
        flight["ATR_20_CH4"] = ch4
        flight["ATR_20_H2O"] = h2o

        return FlightWithNonCO2Impact.from_flight(flight)
