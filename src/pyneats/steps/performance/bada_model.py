from __future__ import annotations

import logging
from typing import Any
import numpy as np
import pandas as pd
from numpy.typing import NDArray
from pycontrails import Flight
from pycontrails.physics.jet import (acceleration as pc_acceleration,
                                     overall_propulsion_efficiency)

from pyneats.core.steps import BaseStep
from pyneats.utils.utilities import is_nan_string
from pyneats.steps.weather.weather_provider import FlightWithWeather
from pyneats.steps.performance.views import FlightWithPerformance
from pyneats.steps.performance.protocol import PerformanceModel
from pyneats.steps.performance.params import BADAPerformanceModelParams
from pyneats.steps.performance.adapters import (BaseBADAAdapter,
                                                BADA3Adapter,
                                                BADA4Adapter,
                                                PerformanceStepError)
from pyneats.core.steps_registry import register

__all__ = ["BADAPerformanceModel"]

logger = logging.getLogger(__name__)

@register(PerformanceModel, "bada")
class BADAPerformanceModel(BaseStep[FlightWithWeather, FlightWithPerformance]):
    """
    Thin wrapper over your BADA adapter.

    - input:  FlightWithWeather (validated upstream)
    - output: FlightWithPerformance (validated here, zero-copy)

    Wire your pyBADA adapter inside `run()`: compute columns and attach to `out`.
    """

    def __init__(self, params: BADAPerformanceModelParams | None = None) -> None:
        super().__init__()
        self.params = params or BADAPerformanceModelParams()
        # self._impl = YourBADAAdapter(self.params)  # when ready


    # public API
    def run(self, flight: FlightWithWeather) -> FlightWithPerformance:
        
        try:
            df = self._preprocess(flight)  # shallow copy + derived columns
            icao = flight.attrs.get("aircraft_type")
            if not icao:
                raise KeyError("Flight attrs missing 'aircraft_type'")

            adapter, bada_version = self._get_bada_adapter(icao)

            perf = self._thrust_fuel_flight(adapter, df)

            # attach results (no deep copy)
            df["fuel_flow"] = perf["fuel_flow"]
            df["fuel_burn"] = df["fuel_flow"] * df["segment_duration"]
            df["thrust"] = perf["thrust"]
            df["aircraft_mass"] = perf["mass"]
            df["phase"] = perf["phase"]
            df["thrust_segment"] = perf["segment"]

            # efficiency (unchanged call)
            tas: NDArray[np.floating]   = df["true_airspeed"].to_numpy(dtype=float, copy=False)
            thrust: NDArray[np.floating] = df["thrust"].to_numpy(dtype=float, copy=False)
            ff: NDArray[np.floating]     = df["fuel_flow"].to_numpy(dtype=float, copy=False)

            df["engine_efficiency"] = overall_propulsion_efficiency(
                tas, thrust, ff, self.params.q_fuel, False, threshold=0.5
            )

            # optional backward-compatibility alias
            if "fuel" not in df and "fuel_burn" in df:
                df["fuel"] = df["fuel_burn"]

            out = Flight(data=df, attrs={**flight.attrs})
            out.attrs["n_engine"] = adapter.nb_eng
            out.attrs["wingspan"] = adapter.span
            out.attrs["bada_version"] = bada_version
            out.attrs["bada_code"] = adapter.bada_code

            # validate core cols; convert to view only when needed
            out = FlightWithPerformance.from_flight(out)

            logger.info(
                "Performance step completed",
                extra={"rows": len(df), "icao": icao, "bada": bada_version},
            )
            return out

        except PerformanceStepError:
            raise
        except Exception as e:
            logger.exception("Performance evaluation failed")
            raise PerformanceStepError(f"Performance evaluation failed: {e}") from e

    # internals (unchanged math flow)
    def _get_bada_adapter(self, icao: str) -> tuple[BaseBADAAdapter, str]:
        # We only need the BADA codes here
        _, bada3_code, bada4_code, _ = self.params.bada_type(icao)

        if is_nan_string(bada4_code):
            return BADA3Adapter(self.params.bada3_config_path, bada3_code), "BADA3"
        return BADA4Adapter(self.params.bada4_config_path, bada4_code), "BADA4"

    def _preprocess(self, flight: Flight) -> pd.DataFrame:
        
        # shallow copy to avoid mutating user input; we’ll add cols here
        df = flight.dataframe.copy(deep=False)

        # Ground speed (PyContrails)
        df["ground_speed"] = flight.segment_groundspeed()

        # True airspeed (PyContrails) with smoothing identical to legacy
        # Coerce once (stays zero-copy if already float-dtype)
        u: NDArray[np.floating] = df["u_wind"].to_numpy(dtype=float, copy=False)
        v: NDArray[np.floating] = df["v_wind"].to_numpy(dtype=float, copy=False)

        df["true_airspeed"] = flight.segment_true_airspeed(
            u_wind=u,
            v_wind=v,
            smooth=True,
            window_length=self.params.true_air_speed_smoothing_window,
            polyorder=1,
        )

        # Durations & kinematics
        df["segment_duration"] = flight.segment_duration()
        df["rocd"] = flight.segment_rocd()

        # Ensure numeric dtype (no-op if already float)
        df["true_airspeed"] = pd.to_numeric(df["true_airspeed"], errors="coerce")
        df["segment_duration"] = pd.to_numeric(df["segment_duration"], errors="coerce")

        tas: NDArray[np.floating] = df["true_airspeed"].to_numpy(dtype=float, copy=False)
        dt: NDArray[np.floating] = df["segment_duration"].to_numpy(dtype=float, copy=False)

        df["acceleration"] = pc_acceleration(tas, dt)

        # legacy code expected this, keep the column name
        df["delta_tau"] = 0.0

        return df

    def _thrust_fuel_flight(self, adapter: BaseBADAAdapter, df: pd.DataFrame) -> dict[str, list[Any]]:
        payload_factor: float = 0.867
        mass_curr: float = payload_factor * float(adapter.MTOW)

        n = len(df)
        mass_arr = [0.0] * n
        ff_arr = [0.0] * n
        thrust_arr = [0.0] * n
        phase_arr = [""] * n
        segment_arr = [""] * n

        def _as_float(x: Any) -> float:
            return float(np.asarray(x, dtype=float))

        # ensure numeric dtype for all needed columns
        cols = ["altitude", "true_airspeed", "rocd", "acceleration", "delta_tau", "segment_duration"]
        df[cols] = df[cols].apply(pd.to_numeric, errors="coerce").astype("float64")

        for idx, pt in enumerate(df.itertuples(index=False, name="FlightPt")):
            ff, thrust, phase, thrust_seg = adapter.thrust_fuel_segment(
                mass_curr,
                _as_float(pt.altitude),
                _as_float(pt.true_airspeed),
                _as_float(pt.rocd),
                _as_float(pt.acceleration),
                _as_float(pt.delta_tau),
            )

            mass_arr[idx] = mass_curr
            ff_arr[idx] = ff
            thrust_arr[idx] = thrust
            phase_arr[idx] = phase
            segment_arr[idx] = thrust_seg

            mass_curr -= _as_float(ff) * _as_float(pt.segment_duration)

        return {
            "mass": mass_arr,
            "fuel_flow": ff_arr,
            "thrust": thrust_arr,
            "phase": phase_arr,
            "segment": segment_arr,
        }