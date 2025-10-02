from __future__ import annotations

from typing import Any, Literal
from functools import cached_property
from dataclasses import dataclass, field
from importlib.resources import files
import numpy as np
import pandas as pd
from numpy.typing import NDArray
from pycontrails import Flight
from pycontrails.physics.units import m_to_T_isa
from pycontrails.physics.jet import (
    acceleration as pc_acceleration,
    overall_propulsion_efficiency,
)

from pyneats.core.neats_defaults import (
    DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW,
    DEFAULT_Q_FUEL,
    DEFAULT_DELTA_TAU_COMPUTE_METHOD,
    DEFAULT_DELTA_TAU_FILL_METHOD,
)
from pyneats.core.steps_registry import register
from pyneats.core.steps import BaseStep
from pyneats.utils.utilities import is_nan_string
from pyneats.steps.weather.weather_provider import FlightWithWeather
from pyneats.steps.performance.views import FlightWithPerformance
from pyneats.steps.performance.protocol import PerformanceModel, PerformanceStepError
from pyneats.steps.performance.params import PerformanceModelParams

from pyneats.steps.performance.adapters import (
    BaseBADAAdapter,
    BADA3Adapter,
    BADA4Adapter,
)

__all__ = [
    "BADAPerformanceModel",
    "BADAPerformanceModelParams",
]


@dataclass(frozen=True)
class BADAPerformanceModelParams(PerformanceModelParams):
    true_air_speed_smoothing_window: int = DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW
    q_fuel: float = DEFAULT_Q_FUEL

    delta_tau_compute_method: Literal["point", "zero"] = (
        DEFAULT_DELTA_TAU_COMPUTE_METHOD
    )
    delta_tau_fill_method: Literal["bffill", "none", "zero"] = (
        DEFAULT_DELTA_TAU_FILL_METHOD
    )

    bada_mapping_file: str = str(
        files("pyneats.ressources").joinpath("mapping_bada.csv")
    )
    bada4_config_path: str = str(files("pyBADA").joinpath("4.2.1")) + "/"
    bada3_config_path: str = str(files("pyBADA").joinpath("3.16")) + "/"

    @cached_property
    def _bada_df(self) -> pd.DataFrame:
        return pd.read_csv(self.bada_mapping_file)

    def bada_type(self, icao: str) -> tuple[int, str, str, str]:
        # expects a mapping df with columns: ICAO, NB_ENG, BADA3, BADA4, ENGINE_ID
        df: pd.DataFrame = self._bada_df
        cols = ["NB_ENG", "BADA3", "BADA4", "ENGINE_ID"]
        row = df.loc[df["ICAO"] == icao, cols]
        if row.empty:
            raise KeyError(f"No entry for ICAO '{icao}'")
        s = row.iloc[0]
        return int(s["NB_ENG"]), str(s["BADA3"]), str(s["BADA4"]), str(s["ENGINE_ID"])


@register(PerformanceModel, "bada")
class BADAPerformanceModel(
    BaseStep[
        FlightWithWeather,
        FlightWithPerformance,
        BADAPerformanceModelParams,
    ]
):
    """
    Thin wrapper over your BADA adapter.

    - input:  FlightWithWeather (validated upstream)
    - output: FlightWithPerformance (validated here, zero-copy)

    Wire your pyBADA adapter inside `run()`: compute columns and attach to `out`.
    """

    default_params = BADAPerformanceModelParams

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
            tas: NDArray[np.floating] = df["true_airspeed"].to_numpy(
                dtype=float, copy=False
            )
            thrust: NDArray[np.floating] = df["thrust"].to_numpy(
                dtype=float, copy=False
            )
            ff: NDArray[np.floating] = df["fuel_flow"].to_numpy(dtype=float, copy=False)

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

            self.logger.info(
                "Performance step completed",
                extra={"rows": len(df), "icao": icao, "bada": bada_version},
            )
            return out

        except PerformanceStepError:
            raise
        except Exception as e:
            self.logger.exception("Performance evaluation failed")
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

        tas: NDArray[np.floating] = df["true_airspeed"].to_numpy(
            dtype=float, copy=False
        )
        dt: NDArray[np.floating] = df["segment_duration"].to_numpy(
            dtype=float, copy=False
        )

        df["acceleration"] = pc_acceleration(tas, dt)

        # legacy code expected this, keep the column name

        if self.params.delta_tau_compute_method == "point":
            # Compute temperature according to ISA
            T_isa: NDArray[np.floating] = m_to_T_isa(
                df["altitude"].to_numpy(dtype=float, copy=False)
            )
            df["delta_tau"] = df["air_temperature"] - T_isa

            # Then fill missing
            if self.params.delta_tau_fill_method == "bffill":
                df["delta_tau"] = df["delta_tau"].ffill().bfill().fillna(0.0)
            elif self.params.delta_tau_fill_method == "zero":
                df["delta_tau"] = df["delta_tau"].fillna(0.0)
        else:
            df["delta_tau"] = 0.0

        return df

    def _thrust_fuel_flight(
        self,
        adapter: BaseBADAAdapter,
        df: pd.DataFrame,
    ) -> dict[str, list[Any]]:
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
        cols = [
            "altitude",
            "true_airspeed",
            "rocd",
            "acceleration",
            "delta_tau",
            "segment_duration",
        ]
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
