from __future__ import annotations

from typing import Any, Literal
from functools import cached_property
from dataclasses import dataclass
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
from pathlib import Path
from pyneats.core.neats_defaults import (
    DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW,
    DEFAULT_Q_FUEL,
    DEFAULT_DELTA_TAU_COMPUTE_METHOD,
    DEFAULT_DELTA_TAU_FILL_METHOD,
    DEFAULT_PAYLOAD_FACTOR,
    DEFAULT_FUEL_RESERVE_FRACTION,
    DEFAULT_MAX_MASS_ESTIMATION_ITER,
    DEFAULT_MAX_REL_MASS_DIFF,
    DEFAULT_BADA4_VERSION,
    DEFAULT_BADA3_VERSION,
    DEFAULT_ROCD_PHASE_THRESHOLD,
)
from pyneats.core.steps_registry import register
from pyneats.core.steps import BaseStep
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


def is_nan_string(s: str) -> bool:
    try:
        return np.isnan(float(s))
    except ValueError:
        return False  # If the string cannot be converted to float, it's not NaN.


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

    bada4_version: str = DEFAULT_BADA4_VERSION
    bada3_version: str = DEFAULT_BADA3_VERSION

    # bada4_config_path: str = str(files("pyBADA").joinpath("4.2.1")) + "/"
    # bada4_config_path: str = str(files("pyBADA").joinpath("4.2.1")) + "/"
    bada4_root_path: str = (
        str(files("pyBADA")) + "/"
    )  # NOTE: this is the base path where the various BADA4 version folders are located. Should it have a default value?
    bada3_root_path: str = str(files("pyBADA")) + "/"  # Same but for BADA3

    # For initial mass estimation
    payload_factor: float = DEFAULT_PAYLOAD_FACTOR
    fuel_reserve_fraction: float = DEFAULT_FUEL_RESERVE_FRACTION
    max_rel_mass_diff: float = DEFAULT_MAX_REL_MASS_DIFF
    max_mass_estimation_iter: int = DEFAULT_MAX_MASS_ESTIMATION_ITER
    rocd_phase_threshold: float = DEFAULT_ROCD_PHASE_THRESHOLD

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

    def _post_init(self):
        # Define BADA paths based on the BADA version, and validate
        super()._post_init()  # pyright: ignore[reportPrivateUsage]

        self.bada4_path = Path(self.params.bada4_root_path).joinpath(
            self.params.bada4_version
        )
        self.bada3_path = Path(self.params.bada3_root_path).joinpath(
            self.params.bada3_version
        )

        # Some checks
        if not self.bada4_path.exists() or not self.bada4_path.is_dir():
            raise PerformanceStepError(
                f"BADA4 path '{self.bada4_path}' does not exist or is not a directory"
            )

        if not self.bada3_path.exists() or not self.bada3_path.is_dir():
            raise PerformanceStepError(
                f"BADA3 path '{self.bada3_path}' does not exist or is not a directory"
            )

        # Loop for all xml and OPF in paths
        # to build the mapping

    # public API
    def run(self, flight: FlightWithWeather) -> FlightWithPerformance:
        try:
            # We need to preprocess anyway the flight to get the true airspeed
            # even if fuel flow and enngine_efficiency are provided
            # the true airspeed is needed in downstream steps, and so is part of the view
            df = self._preprocess(flight)  # shallow copy + derived columns

            # We need this to get the number of engines and span, which are required by downstream
            icao = flight.attrs.get("aircraft_type")
            q_fuel: float | None = flight.attrs.get("q_fuel")

            if not icao:
                raise KeyError("Flight attrs missing 'aircraft_type'")

            adapter, bada_version = self._get_bada_adapter(icao)

            # If both fuel_flow and engine_efficiency are provided by AOs, stop here
            if "fuel_flow" in df.columns and "engine_efficiency" in df.columns:
                self.logger.debug(
                    "Flight already has 'fuel_flow' and 'engine_efficiency', skipping BADA model",
                    extra={"rows": len(df)},
                )

                df["fuel_burn"] = df["fuel_flow"] * df["segment_duration"]

                # optional backward-compatibility alias
                if "fuel" not in df.columns and "fuel_burn" in df.columns:
                    df["fuel"] = df["fuel_burn"]

                out = Flight(data=df, attrs={**flight.attrs})
                out.attrs["n_engine"] = adapter.nb_eng
                out.attrs["wingspan"] = adapter.span
                return FlightWithPerformance.from_flight(out)

            # When fuel_flow and/or emgine_efficiency are missing, we need to run BADA
            if "aircraft_mass" in df.columns:
                self.logger.debug("'aircraft_mass' column provided, using it")

                # Aircraft mass is known all along the trajectory. Just one BADA pass
                perf = self._thrust_fuel_flight(
                    adapter,
                    df,
                    initial_mass=None,  # use column values
                )
            else:
                # Get take-off weight if available
                initial_mass: float | None = flight.attrs.get("takeoff_weight")

                # Initial mass is provided
                if initial_mass is not None:
                    self.logger.debug("'takeoff_weight' attribute provided, using it")

                    # Initial mass is known. Just one BADA pass
                    # No need to iterate
                    perf = self._thrust_fuel_flight(
                        adapter,
                        df,
                        initial_mass=initial_mass,
                    )
                else:
                    # Use provided payload factor or default
                    payload_factor: float | None = flight.attrs.get("payload_factor")

                    if payload_factor is not None:
                        self.logger.debug(
                            "'payload_factor' attribute provided, using it"
                        )
                    else:
                        payload_factor = self.params.payload_factor

                    # Constant values from BADA
                    operating_empty_weight = adapter.OEW
                    maximum_takeoff_weight = adapter.MTOW

                    if operating_empty_weight is None or maximum_takeoff_weight is None:
                        raise PerformanceStepError(
                            f"BADA adapter for ICAO '{icao}' does not provide OEW or MTOW"
                        )

                    if adapter.MPL is None:
                        self.logger.warning(
                            f"""BADA adapter for ICAO '{icao}' does not provide MPL,  # pylint: disable=logging-fstring-interpolation
                            assuming MPL = MTOW - OEW. Conservative case"""  # pylint: disable=logging-fstring-interpolation
                        )
                        maximum_payload = (
                            maximum_takeoff_weight - operating_empty_weight
                        )
                    else:
                        maximum_payload = adapter.MPL

                    # Other constants
                    zero_fuel_weight: float = (
                        operating_empty_weight + payload_factor * maximum_payload
                    )
                    fuel_factor: float = 1.0 + self.params.fuel_reserve_fraction

                    # Conservative initial mass guess
                    initial_mass = operating_empty_weight + payload_factor * (
                        maximum_takeoff_weight - operating_empty_weight
                    )

                    # Store previous mass
                    prev_mass = initial_mass

                    # First iteration, using constant mass assumption according to documentation
                    perf = self._thrust_fuel_flight(
                        adapter,
                        df.assign(aircraft_mass=initial_mass),
                        initial_mass=None,  # use column values (constant here)
                    )

                    # Compute initial fuel onboard estimate
                    fuel_consumed = float(
                        (perf["fuel_flow"] * df["segment_duration"]).sum()
                    )
                    fuel_onboard = fuel_consumed * fuel_factor  # Consider the reserves

                    # Initial mass estimate = zero fuel weight + estimated fuel onboard
                    initial_mass = min(
                        maximum_takeoff_weight, zero_fuel_weight + fuel_onboard
                    )  # Clip to MTOW

                    self.logger.debug(
                        f"Initial mass estimate: {initial_mass} kg. MTOW: {maximum_takeoff_weight} kg"
                    )
                    # pylint: enable=logging-fstring-interpolation

                    rel_mass_diff = float("inf")  # Force loop entry
                    iter_count = 1

                    while (
                        rel_mass_diff > self.params.max_rel_mass_diff
                        and iter_count < self.params.max_mass_estimation_iter
                    ):
                        # Store previous mass
                        prev_mass = initial_mass

                        # Compute performance using current TOW estimate
                        perf = self._thrust_fuel_flight(
                            adapter,
                            df,
                            initial_mass=initial_mass,
                        )

                        fuel_consumed = float(
                            (perf["fuel_flow"] * df["segment_duration"]).sum()
                        )
                        fuel_onboard = fuel_consumed * fuel_factor

                        # Update mass estimate
                        initial_mass = min(
                            maximum_takeoff_weight, zero_fuel_weight + fuel_onboard
                        )

                        # Compute relative difference
                        rel_mass_diff = abs(prev_mass - initial_mass) / prev_mass

                        self.logger.debug(
                            f"Mass estimation iteration {iter_count}: {initial_mass} kg (diff {rel_mass_diff * 100}%)",
                        )

                        iter_count += 1

            # Adjusting fuel flow if q_fuel attribute provided
            if q_fuel is not None:
                self.logger.debug(
                    f"'q_fuel' attribute provided ({q_fuel} J/kg), multiplying the fuel flow with the ratio with default value{self.params.q_fuel} J/kg"
                )
                if q_fuel != self.params.q_fuel:
                    q_fuel_ratio = q_fuel / self.params.q_fuel
                    perf["fuel_flow"] = (
                        np.asarray(perf["fuel_flow"], dtype=float) / q_fuel_ratio
                    ).tolist()
            else:
                q_fuel = self.params.q_fuel

            df["thrust"] = perf["thrust"]
            df["aircraft_mass"] = perf["mass"]
            df["phase"] = perf["phase"]
            df["thrust_segment"] = perf["segment"]

            # Set computed engine_efficiency if not provided by AO
            if "engine_efficiency" not in df.columns:
                # efficiency (unchanged call)
                tas: NDArray[np.floating] = df["true_airspeed"].to_numpy(
                    dtype=float, copy=False
                )
                thrust: NDArray[np.floating] = df["thrust"].to_numpy(
                    dtype=float, copy=False
                )

                # Use the BADA-computed fuel flow even if AO provided it
                ff: NDArray[np.floating] = np.asarray(perf["fuel_flow"], dtype=float)

                df["engine_efficiency"] = overall_propulsion_efficiency(
                    tas,
                    thrust,
                    ff,
                    q_fuel,
                    False,
                    threshold=0.5,
                )
            else:
                self.logger.debug(
                    "'engine_efficiency' column already provided, keeping it"
                )

            # Set BADA-computed fuel_flow only if not provided by AO
            if "fuel_flow" not in df.columns:
                df["fuel_flow"] = perf["fuel_flow"]
            else:
                self.logger.debug("'fuel_flow' column already provided, keeping it")

            df["fuel_burn"] = (
                df["fuel_flow"] * df["segment_duration"]
            )  # Always consistent with fuel_flow, whichever the source

            # optional backward-compatibility alias
            if "fuel" not in df.columns and "fuel_burn" in df.columns:
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
        except PerformanceStepError:
            raise
        except Exception as e:
            self.logger.exception("Performance evaluation failed")
            raise PerformanceStepError(f"Performance evaluation failed: {e}") from e

        return out

    # internals (unchanged math flow)
    def _get_bada_adapter(self, icao: str) -> tuple[BaseBADAAdapter, str]:
        # We only need the BADA codes here
        _, bada3_code, bada4_code, _ = self.params.bada_type(icao)

        if is_nan_string(bada4_code):
            return BADA3Adapter(
                str(self.bada3_path),
                bada3_code,
                rocd_phase_threshold=self.params.rocd_phase_threshold,
            ), "BADA3"

        return BADA4Adapter(
            str(self.bada4_path),
            bada4_code,
            rocd_phase_threshold=self.params.rocd_phase_threshold,
        ), "BADA4"

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
        df["rocd"] = flight.segment_rocd()  # NOTE: requires air temperature?

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
        initial_mass: float | None = None,
    ) -> dict[str, list[Any]]:
        # Check inputs
        if initial_mass is None and "aircraft_mass" not in df.columns:
            raise PerformanceStepError(
                "Initial mass not provided and 'aircraft_mass' column missing"
            )
        elif initial_mass is not None and "aircraft_mass" in df.columns:
            self.logger.warning(
                "Both initial mass and 'aircraft_mass' column provided; ignoring initial mass"
            )
            initial_mass = None

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

        # also aircraft_mass if available
        if "aircraft_mass" in df.columns:
            cols.append("aircraft_mass")

        df[cols] = df[cols].apply(pd.to_numeric, errors="coerce").astype("float64")

        # Initial mass
        mass_curr = initial_mass

        for idx, pt in enumerate(df.itertuples(index=False, name="FlightPt")):
            # Current mass: from column if available, else from tracking variable
            pt_mass = (
                mass_curr if mass_curr is not None else _as_float(pt.aircraft_mass)
            )

            ff, thrust, phase, thrust_seg = adapter.thrust_fuel_segment(
                pt_mass,
                _as_float(pt.altitude),
                _as_float(pt.true_airspeed),
                _as_float(pt.rocd),
                _as_float(pt.acceleration),
                _as_float(pt.delta_tau),
            )

            mass_arr[idx] = pt_mass
            ff_arr[idx] = ff
            thrust_arr[idx] = thrust
            phase_arr[idx] = phase
            segment_arr[idx] = thrust_seg

            # Update current mass if tracking
            if mass_curr is not None:
                mass_curr -= _as_float(ff) * _as_float(pt.segment_duration)

        return {
            "mass": mass_arr,
            "fuel_flow": ff_arr,
            "thrust": thrust_arr,
            "phase": phase_arr,
            "segment": segment_arr,
        }
