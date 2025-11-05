from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict, Optional, Tuple
from dataclasses import dataclass
from importlib.resources import files
import numpy as np
import pandas as pd
from numpy.typing import NDArray


from pycontrails import Flight
from pycontrails.physics.units import m_to_T_isa, ft_to_m
from pycontrails.physics.jet import (
    acceleration as pc_acceleration,
    overall_propulsion_efficiency,
)

from pyneats.core.neats_default_parameters import (
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

from pyneats.steps.performance.bada_adapters import (
    BaseBADAAdapter,
    BADA3Adapter,
    BADA4Adapter,
    FlightPhase,
)

from pyneats.steps.performance.bada_mapper import BadaMappingPaths, BadaMapper


__all__ = [
    "BADAPerformanceModel",
    "BADAPerformanceModelParams",
]

# -----------------------------
# Types
# -----------------------------


class PerfOutput(TypedDict):
    mass: list[float]
    fuel_flow: list[float]
    thrust: list[float]
    phase: list[FlightPhase]
    segment: list[str]


# -----------------------------
# Small helpers
# -----------------------------


def _as_float(x: Any) -> float:
    return float(np.asarray(x, dtype=float))


def _normalize_code_or_none(code: Optional[str]) -> Optional[str]:
    if code is None:
        return None
    s = str(code).strip()
    if not s:
        return None
    # handle common "nan" strings
    if s.lower() in {"nan", "none", "null"}:
        return None
    return s


# -----------------------------
# Params
# -----------------------------


@dataclass(frozen=True)
class BADAPerformanceModelParams(PerformanceModelParams):
    true_air_speed_smoothing_window: int = DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW
    q_fuel: float = DEFAULT_Q_FUEL

    delta_tau_compute_method: Literal["point", "zero"] = DEFAULT_DELTA_TAU_COMPUTE_METHOD
    delta_tau_fill_method: Literal["bffill", "none", "zero"] = DEFAULT_DELTA_TAU_FILL_METHOD

    # BADA mapping paths (to packaged resources)
    icao_series_engine_path = Path(
        str(files("pyneats.resources").joinpath("ECTL_mapping_by_ACFT_SERIES_and_ENGINE_ID.csv"))
    )
    icao_series_path = Path(
        str(files("pyneats.resources").joinpath("ECTL_mapping_by_ACFT_SERIES.csv"))
    )
    icao_engine_path = Path(
        str(files("pyneats.resources").joinpath("ECTL_mapping_by_ENGINE_ID_and_ICAO.csv"))
    )
    default_engine_by_icao_path = Path(
        str(files("pyneats.resources").joinpath("MRR_conservative_mapping.csv"))
    )
    icao_only_path = Path(str(files("pyneats.resources").joinpath("ECTL_mapping_by_ICAO.csv")))

    paths = BadaMappingPaths(
        icao_series_engine=icao_series_engine_path,
        icao_series=icao_series_path,
        icao_engine=icao_engine_path,
        default_engine_by_icao=default_engine_by_icao_path,
        icao_only=icao_only_path,
    )

    mapper = BadaMapper(paths)

    bada4_version: str = DEFAULT_BADA4_VERSION
    bada3_version: str = DEFAULT_BADA3_VERSION

    bada4_root_path: str = str(files("pyBADA")) + "/"
    bada3_root_path: str = str(files("pyBADA")) + "/"

    # For initial mass estimation
    payload_factor: float = DEFAULT_PAYLOAD_FACTOR
    fuel_reserve_fraction: float = DEFAULT_FUEL_RESERVE_FRACTION
    max_rel_mass_diff: float = DEFAULT_MAX_REL_MASS_DIFF
    max_mass_estimation_iter: int = DEFAULT_MAX_MASS_ESTIMATION_ITER
    rocd_phase_threshold: float = DEFAULT_ROCD_PHASE_THRESHOLD

    def bada_type(
        self,
        icao: str,
        series: str | None,
        engine_id: str | None,
    ) -> tuple[int, str, str, str]:
        return self.mapper.bada_type(icao, series, engine_id)


@register(PerformanceModel, "bada")
class BADAPerformanceModel(
    BaseStep[
        FlightWithWeather,
        FlightWithPerformance,
        BADAPerformanceModelParams,
    ]
):
    """
    Thin wrapper over BADA adapters with a refactored, testable structure.
    """

    default_params = BADAPerformanceModelParams

    # ---------- lifecycle ----------
    def _post_init(self):
        super()._post_init()  # pyright: ignore[reportPrivateUsage]

        self.bada4_path = Path(self.params.bada4_root_path).joinpath(self.params.bada4_version)
        self.bada3_path = Path(self.params.bada3_root_path).joinpath(self.params.bada3_version)

        if not self.bada4_path.exists() or not self.bada4_path.is_dir():
            raise PerformanceStepError(
                f"BADA4 path '{self.bada4_path}' does not exist or is not a directory"
            )

        if not self.bada3_path.exists() or not self.bada3_path.is_dir():
            raise PerformanceStepError(
                f"BADA3 path '{self.bada3_path}' does not exist or is not a directory"
            )

    # ---------- public API ----------
    def run(self, flight: FlightWithWeather) -> FlightWithPerformance:
        try:
            # 1) preprocess
            df = self._preprocess(flight)

            # 2) resolve adapter + core attrs
            icao, series, engine_id_attr, q_fuel_attr = self._extract_aircraft_attrs(flight)
            adapter, bada_version, nb_eng, engine_id = self._resolve_bada_adapter(
                icao, series, engine_id_attr
            )

            # 3) early exit if AO provided fuel_flow & engine_efficiency
            early = self._early_exit_if_fuel_and_efficiency(df, adapter, engine_id, flight)
            if early is not None:
                return early

            # 4) choose mass strategy + compute perf
            perf = self._choose_mass_strategy(adapter, df, flight, icao)

            # 5) apply q_fuel correction if provided
            q_fuel_used = self._apply_q_fuel_adjustment(perf, q_fuel_attr, self.params.q_fuel)

            # 6) finalize df columns, compute efficiency if needed
            self._finalize_columns(df, perf)
            self._compute_engine_efficiency_if_missing(df, perf, q_fuel_used)

            # 7) build Flight output
            out = Flight(data=df, attrs={**flight.attrs}, fuel=flight.fuel)
            self._attach_output_attrs(out, adapter, bada_version, nb_eng, engine_id)

            out_view = FlightWithPerformance.from_flight(out)

            self.logger.info(
                "Performance step completed",
                extra={"rows": len(df), "icao": icao, "bada": bada_version},
            )
            return out_view

        except PerformanceStepError:
            raise
        except Exception as e:  # pylint: disable=broad-except
            self.logger.exception("Performance evaluation failed")
            raise PerformanceStepError(f"Performance evaluation failed: {e}") from e

    # ---------- adapter & attrs ----------
    def _extract_aircraft_attrs(
        self, flight: Flight
    ) -> Tuple[str, Optional[str], Optional[str], Optional[float]]:
        icao: Optional[str] = (
            flight.attrs.get("aircraft_type") if hasattr(flight, "attrs") else None
        )
        if not icao:
            raise KeyError("Flight attrs missing 'aircraft_type'")

        series: Optional[str] = flight.attrs.get("series") if hasattr(flight, "attrs") else None
        engine_id: Optional[str] = (
            flight.attrs.get("engine_id") if hasattr(flight, "attrs") else None
        )
        q_fuel: Optional[float] = flight.attrs.get("q_fuel") if hasattr(flight, "attrs") else None
        return icao, series, engine_id, q_fuel

    def _resolve_bada_adapter(
        self, icao: str, series: Optional[str], engine_id: Optional[str]
    ) -> tuple[BaseBADAAdapter, str, int, str]:
        nb_eng, bada3_code, bada4_code, resolved_engine = self.params.bada_type(
            icao, series=series, engine_id=engine_id
        )
        bada4_code = _normalize_code_or_none(bada4_code)

        if bada4_code is None:
            adapter: BaseBADAAdapter = BADA3Adapter(
                str(self.bada3_path),
                bada3_code,
                rocd_phase_threshold_fpm=self.params.rocd_phase_threshold,
            )
            return adapter, "BADA3", nb_eng, resolved_engine

        adapter = BADA4Adapter(
            str(self.bada4_path),
            bada4_code,
            rocd_phase_threshold_fpm=self.params.rocd_phase_threshold,
        )
        return adapter, "BADA4", nb_eng, resolved_engine

    # ---------- preprocessing ----------
    def _preprocess(self, flight: Flight) -> pd.DataFrame:
        df = self._compute_ground_and_true_airspeed(
            flight,
            self.params.true_air_speed_smoothing_window,
        )
        self._compute_kinematics(flight, df)
        self._compute_delta_tau(
            df,
            self.params.delta_tau_compute_method,
            self.params.delta_tau_fill_method,
        )
        return df

    def _compute_ground_and_true_airspeed(self, flight: Flight, window: int) -> pd.DataFrame:
        df = flight.dataframe.copy(deep=False)
        df["ground_speed"] = flight.segment_groundspeed()

        u: NDArray[np.floating] = df["u_wind"].to_numpy(dtype=float, copy=False)
        v: NDArray[np.floating] = df["v_wind"].to_numpy(dtype=float, copy=False)

        df["true_airspeed"] = flight.segment_true_airspeed(
            u_wind=u,
            v_wind=v,
            smooth=True,
            window_length=window,
            polyorder=1,
        )

        # ensure numeric dtype early
        df["true_airspeed"] = pd.to_numeric(df["true_airspeed"], errors="coerce")
        return df

    def _compute_kinematics(self, flight: Flight, df: pd.DataFrame) -> None:
        df["segment_duration"] = flight.segment_duration()
        df["rocd"] = flight.segment_rocd()
        df["segment_duration"] = pd.to_numeric(df["segment_duration"], errors="coerce")

        tas: NDArray[np.floating] = df["true_airspeed"].to_numpy(dtype=float, copy=False)
        dt: NDArray[np.floating] = df["segment_duration"].to_numpy(dtype=float, copy=False)
        df["acceleration"] = pc_acceleration(tas, dt)

    def _compute_delta_tau(
        self,
        df: pd.DataFrame,
        method: Literal["point", "zero"],
        fill: Literal["bffill", "zero", "none"],
    ) -> None:
        if method == "point":
            T_isa: NDArray[np.floating] = m_to_T_isa(
                df["altitude"].to_numpy(dtype=float, copy=False)
            )
            df["delta_tau"] = df["air_temperature"] - T_isa

            if fill == "bffill":
                df["delta_tau"] = df["delta_tau"].ffill().bfill().fillna(0.0)
            elif fill == "zero":
                df["delta_tau"] = df["delta_tau"].fillna(0.0)

        else:
            df["delta_tau"] = 0.0

        

    # ---------- early exit when AO provides data ----------
    def _early_exit_if_fuel_and_efficiency(
        self,
        df: pd.DataFrame,
        adapter: BaseBADAAdapter,
        engine_id: str,
        flight: Flight,
    ) -> Optional[FlightWithPerformance]:
        if "fuel_flow" in df.columns and "engine_efficiency" in df.columns:
            self.logger.debug(
                "Flight already has 'fuel_flow' and 'engine_efficiency', skipping BADA model",
                extra={"rows": len(df)},
            )
            df["fuel_burn"] = df["fuel_flow"] * df["segment_duration"]

            if "fuel" not in df.columns and "fuel_burn" in df.columns:
                df["fuel"] = df["fuel_burn"]

            out = Flight(data=df, attrs={**flight.attrs}, fuel=flight.fuel)
            out.attrs["engine_id"] = engine_id
            out.attrs["n_engine"] = adapter.nb_eng
            out.attrs["wingspan"] = adapter.span
            return FlightWithPerformance.from_flight(out)
        return None

    # ---------- mass strategies ----------
    def _choose_mass_strategy(
        self,
        adapter: BaseBADAAdapter,
        df: pd.DataFrame,
        flight: Flight,
        icao: str,
    ) -> PerfOutput:
        # Ensure numeric columns used by thrust_fuel
        cols = [
            "altitude",
            "true_airspeed",
            "rocd",
            "acceleration",
            "delta_tau",
            "segment_duration",
        ]
        if "aircraft_mass" in df.columns:
            cols.append("aircraft_mass")
        df[cols] = df[cols].apply(pd.to_numeric, errors="coerce").astype("float64")

        if "aircraft_mass" in df.columns:
            self.logger.debug("'aircraft_mass' column provided, using it")
            return self._single_pass_performance(adapter, df, initial_mass=None)

        initial_mass: Optional[float] = flight.attrs.get("takeoff_weight")
        if initial_mass is not None:
            self.logger.debug("'takeoff_weight' attribute provided, using it")
            return self._single_pass_performance(adapter, df, initial_mass=initial_mass)

        # iterative estimation
        return self._estimate_initial_mass_iterative(adapter, df, flight, icao)

    def _single_pass_performance(
        self,
        adapter: BaseBADAAdapter,
        df: pd.DataFrame,
        initial_mass: Optional[float],
    ) -> PerfOutput:
        if initial_mass is None and "aircraft_mass" not in df.columns:
            raise PerformanceStepError(
                "Initial mass not provided and 'aircraft_mass' column missing"
            )
        if initial_mass is not None and "aircraft_mass" in df.columns:
            self.logger.warning(
                "Both initial mass and 'aircraft_mass' column provided; ignoring initial mass"
            )
            initial_mass = None

        mass_arr: list[float] = []
        ff_arr: list[float] = []
        thrust_arr: list[float] = []
        phase_arr: list[FlightPhase] = []
        segment_arr: list[str] = []

        mass_curr = initial_mass

        for pt in df.itertuples(index=False, name="FlightPt"):
            pt_mass = mass_curr if mass_curr is not None else _as_float(pt.aircraft_mass)

            ff, thrust, phase, thrust_seg = adapter.thrust_fuel_segment(
                pt_mass,
                _as_float(pt.altitude),
                _as_float(pt.true_airspeed),
                ft_to_m(_as_float(pt.rocd)) / 60,  # Convert ft/min to m/s. The adapter requires SI
                _as_float(pt.acceleration),
                _as_float(pt.delta_tau),
            )

            mass_arr.append(pt_mass)
            ff_arr.append(_as_float(ff))
            thrust_arr.append(_as_float(thrust))
            phase_arr.append(phase)
            segment_arr.append(str(thrust_seg))

            if mass_curr is not None:
                mass_curr -= _as_float(ff) * _as_float(pt.segment_duration)

        return PerfOutput(
            mass=mass_arr,
            fuel_flow=ff_arr,
            thrust=thrust_arr,
            phase=phase_arr,
            segment=segment_arr,
        )

    def _estimate_initial_mass_iterative(
        self,
        adapter: BaseBADAAdapter,
        df: pd.DataFrame,
        flight: Flight,
        icao: str,
    ) -> PerfOutput:
        payload_factor: Optional[float] = flight.attrs.get("payload_factor")

        if payload_factor is None:
            payload_factor = self.params.payload_factor
        else:
            self.logger.debug("'payload_factor' attribute provided, using it")

        operating_empty_weight = adapter.OEW
        maximum_takeoff_weight = adapter.MTOW
        if operating_empty_weight is None or maximum_takeoff_weight is None:
            raise PerformanceStepError(
                f"BADA adapter for ICAO '{icao}' does not provide OEW or MTOW"
            )

        if adapter.MPL is None:
            self.logger.warning(
                f"BADA adapter for ICAO '{icao}' does not provide MPL, assuming MPL = MTOW - OEW. Conservative case"
            )
            maximum_payload = maximum_takeoff_weight - operating_empty_weight
        else:
            maximum_payload = adapter.MPL

        zero_fuel_weight: float = operating_empty_weight + payload_factor * maximum_payload
        fuel_factor: float = 1.0 + self.params.fuel_reserve_fraction

        # Conservative initial mass guess (between OEW and MTOW weighted by payload factor)
        initial_mass_guess = operating_empty_weight + payload_factor * (
            maximum_takeoff_weight - operating_empty_weight
        )

        # First pass with constant mass assumption
        perf = self._single_pass_performance(
            adapter,
            df.assign(aircraft_mass=initial_mass_guess),
            initial_mass=None,
        )
        fuel_consumed = float((np.asarray(perf["fuel_flow"]) * df["segment_duration"]).sum())
        fuel_onboard = fuel_consumed * fuel_factor
        initial_mass = min(maximum_takeoff_weight, zero_fuel_weight + fuel_onboard)

        self.logger.debug(
            f"Initial mass estimate: {initial_mass} kg. MTOW: {maximum_takeoff_weight} kg"
        )

        rel_mass_diff = float("inf")
        iter_count = 1

        while (
            rel_mass_diff > self.params.max_rel_mass_diff
            and iter_count < self.params.max_mass_estimation_iter
        ):
            prev_mass = initial_mass

            perf = self._single_pass_performance(adapter, df, initial_mass=initial_mass)
            fuel_consumed = float((np.asarray(perf["fuel_flow"]) * df["segment_duration"]).sum())
            fuel_onboard = fuel_consumed * fuel_factor
            initial_mass = min(maximum_takeoff_weight, zero_fuel_weight + fuel_onboard)

            rel_mass_diff = abs(prev_mass - initial_mass) / prev_mass
            self.logger.debug(
                f"Mass estimation iteration {iter_count}: {initial_mass} kg (diff {rel_mass_diff * 100}%)"
            )
            iter_count += 1

        return perf

    # ---------- post-processing ----------
    def _apply_q_fuel_adjustment(
        self,
        perf: PerfOutput,
        q_fuel_attr: Optional[float],
        default_q_fuel: float,
    ) -> float:
        q_fuel_used = q_fuel_attr if q_fuel_attr is not None else default_q_fuel
        if q_fuel_attr is not None:
            self.logger.debug(
                f"'q_fuel' attribute provided ({q_fuel_attr} J/kg), comparing to default {default_q_fuel} J/kg"
            )
            if q_fuel_attr != default_q_fuel:
                ratio = q_fuel_attr / default_q_fuel
                # Divide fuel_flow by ratio so that fuel_burn stays physically consistent
                perf["fuel_flow"] = (np.asarray(perf["fuel_flow"], dtype=float) / ratio).tolist()
        return q_fuel_used

    def _compute_engine_efficiency_if_missing(
        self,
        df: pd.DataFrame,
        perf: PerfOutput,
        q_fuel: float,
    ) -> None:
        if "engine_efficiency" in df.columns:
            self.logger.debug("'engine_efficiency' column already provided, keeping it")
            return

        tas: NDArray[np.floating] = df["true_airspeed"].to_numpy(dtype=float, copy=False)
        thrust: NDArray[np.floating] = np.asarray(perf["thrust"], dtype=float)
        ff: NDArray[np.floating] = np.asarray(perf["fuel_flow"], dtype=float)
        is_descent: NDArray[np.bool_] = np.asarray(perf["phase"], dtype=str) == "Descent"

        df["engine_efficiency"] = overall_propulsion_efficiency(
            tas,
            thrust,
            ff,
            q_fuel,
            is_descent=is_descent,
            threshold=0.5,
        )

    def _finalize_columns(self, df: pd.DataFrame, perf: PerfOutput) -> None:
        df["thrust"] = perf["thrust"]
        df["aircraft_mass"] = perf["mass"]
        df["phase"] = perf["phase"]
        df["thrust_segment"] = perf["segment"]

        if "fuel_flow" not in df.columns:
            df["fuel_flow"] = perf["fuel_flow"]
        else:
            self.logger.debug("'fuel_flow' column already provided, keeping it")

        df["fuel_burn"] = df["fuel_flow"] * df["segment_duration"]

        if "fuel" not in df.columns and "fuel_burn" in df.columns:
            df["fuel"] = df["fuel_burn"]

    def _attach_output_attrs(
        self,
        out: Flight,
        adapter: BaseBADAAdapter,
        bada_version: str,
        nb_eng: int,
        engine_id: str,
    ) -> None:
        out.attrs["n_engine"] = nb_eng
        out.attrs["wingspan"] = adapter.span
        out.attrs["bada_version"] = bada_version
        out.attrs["bada_code"] = adapter.bada_code
        out.attrs["engine_id"] = engine_id
