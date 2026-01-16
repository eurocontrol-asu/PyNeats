"""BADA Performance Model Module

This module implements aircraft performance calculations using EUROCONTROL's Base of
Aircraft Data (BADA) models. It provides:

1. Aircraft Performance Computation:
   - Thrust and fuel flow calculation
   - Aircraft mass estimation
   - Flight phase detection
   - Engine efficiency computation
   - Aircraft-specific parameter lookups

2. BADA Model Integration:
   - BADA3 and BADA4 model support
   - Automatic model selection based on aircraft type
   - Fallback mechanisms between versions
   - Engine type resolution

3. Key Features:
   - Iterative mass estimation for unknown initial mass
   - Conservative mass estimation with payload factor
   - Flexible engine efficiency computation
   - Multiple delta-tau computation methods
   - True airspeed smoothing
   - Comprehensive error handling

4. Data Sources:
   - BADA3/4 coefficient files
   - Aircraft mapping tables
   - Engine type databases
   - Default parameters from RSTS
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, TypedDict

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from pycontrails import Flight
from pycontrails.physics.jet import (
    acceleration as pc_acceleration,
)
from pycontrails.physics.jet import (
    overall_propulsion_efficiency,
)
from pycontrails.physics.units import ft_to_m, m_to_T_isa

from pyneats.core.neats_default_parameters import (
    DEFAULT_BADA3_VERSION,
    DEFAULT_BADA4_VERSION,
    DEFAULT_DELTA_TAU_COMPUTE_METHOD,
    DEFAULT_DELTA_TAU_FILL_METHOD,
    DEFAULT_FUEL_RESERVE_FRACTION,
    DEFAULT_MAX_MASS_ESTIMATION_ITER,
    DEFAULT_MAX_REL_MASS_DIFF,
    DEFAULT_PAYLOAD_FACTOR,
    DEFAULT_ROCD_PHASE_THRESHOLD,
    DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW,
    REFERENCE_Q_FUEL,
)
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.performance.bada_adapters import (
    BADA3Adapter,
    BADA4Adapter,
    BaseBADAAdapter,
    FlightPhase,
)
from pyneats.steps.performance.bada_mapper import BadaMapper, BadaMappingPaths
from pyneats.steps.performance.params import PerformanceModelParams
from pyneats.steps.performance.protocol import PerformanceModel, PerformanceStepError
from pyneats.steps.performance.views import FlightWithPerformance
from pyneats.steps.weather.weather_provider import FlightWithWeather

__all__ = [
    "BADAPerformanceModel",
    "BADAPerformanceModelParams",
]

# -----------------------------
# Types
# -----------------------------


class PerfOutput(TypedDict):
    """Output of performance calculation step."""

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


def _normalize_code_or_none(code: str | None) -> str | None:
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
    """Parameters for the BADA performance model calculation."""

    true_air_speed_smoothing_window: int = DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW
    reference_q_fuel: float = REFERENCE_Q_FUEL

    delta_tau_compute_method: Literal["point", "zero"] = (
        DEFAULT_DELTA_TAU_COMPUTE_METHOD
    )
    delta_tau_fill_method: Literal["bffill", "none", "zero"] = (
        DEFAULT_DELTA_TAU_FILL_METHOD
    )

    # BADA mapping paths (to packaged resources)
    icao_series_engine_path = Path(
        str(
            files("pyneats.resources").joinpath(
                "ECTL_mapping_by_ICAO_and_ACFT_SERIES_and_ENGINE_ID.csv"
            )
        )
    )
    icao_series_path = Path(
        str(
            files("pyneats.resources").joinpath(
                "ECTL_mapping_by_ICAO_and_ACFT_SERIES.csv"
            )
        )
    )
    icao_engine_path = Path(
        str(
            files("pyneats.resources").joinpath(
                "ECTL_mapping_by_ICAO_and_ENGINE_ID.csv"
            )
        )
    )
    default_engine_by_icao_path = Path(
        str(files("pyneats.resources").joinpath("MRR_conservative_mapping.csv"))
    )
    icao_only_path = Path(
        str(files("pyneats.resources").joinpath("ECTL_mapping_by_ICAO.csv"))
    )

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
        """Resolve BADA type using the mapper"""

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

        self.bada4_path = Path(self.params.bada4_root_path).joinpath(
            self.params.bada4_version
        )
        self.bada3_path = Path(self.params.bada3_root_path).joinpath(
            self.params.bada3_version
        )

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
        """Run BADA performance model on the given flight data."""

        # --- Preprocessing + aircraft data extraction ---
        try:
            df = self._preprocess(flight)
            icao, series, engine_id_attr, q_fuel_attr = self._extract_aircraft_attrs(
                flight
            )

        except Exception as e:
            self.logger.info(
                "Preprocessing and aircraft attribute extraction failed during Performance evaluation" # noqa: E501
            )

            raise PerformanceStepError(
                f"Preprocessing and aircraft attribute extraction failed during Performance evaluation: {e}" # noqa: E501
            ) from e

        # --- First attempt: normal BADA (3 or 4) execution ---
        try:
            return self.run_by_bada_version(
                flight, df, icao, series, engine_id_attr, q_fuel_attr
            )

        except PerformanceStepError as exc:
            self.logger.info(
                "BADA performance evaluation failed. Retrying BADA performance evaluation with BADA3 enforced", # noqa: E501
                extra={"icao": icao, "series": series, "engine_id": engine_id_attr},
            )

            # Try to determine whether BADA4 is missing
            try:
                _, _, bada4_code, _ = self.params.bada_type(
                    icao, series=series, engine_id=engine_id_attr
                )
                bada4_code = _normalize_code_or_none(bada4_code)

                if bada4_code is None:
                    self.logger.info(
                        "BADA performance evaluation already performed with BADA3, no need to retry with BADA3 again", # noqa: E501
                        extra={
                            "icao": icao,
                            "series": series,
                            "engine_id": engine_id_attr,
                        },
                    )
                    raise PerformanceStepError(
                        "BADA performance evaluation already performed with BADA3, no need to retry with BADA3 again" # noqa: E501
                    ) from exc

                return self.run_by_bada_version(
                    flight,
                    df,
                    icao,
                    series,
                    engine_id_attr,
                    q_fuel_attr,
                    force_bada3=True,
                )

            except Exception as exc2:
                raise PerformanceStepError(
                    f"BADA performance evaluation failed with both BADA4 and BADA3 "
                    f"(underlying error: {exc2})"
                ) from exc2

    def run_by_bada_version(
        self,
        flight: FlightWithWeather,
        df: pd.DataFrame,
        icao: str,
        series: str | None,
        engine_id_attr: str | None,
        q_fuel_attr: float | None,
        force_bada3: bool = False,
    ) -> FlightWithPerformance:
        """Run BADA performance model on the given flight data, with optional BADA3 enforcement."""

        try:
            # 1) resolve adapter + core attrs
            adapter, bada_version, nb_eng, engine_id = self._resolve_bada_adapter(
                icao, series, engine_id_attr, force_bada3
            )

            # 2) early exit if AO provided fuel_flow & engine_efficiency
            early = self._early_exit_if_fuel_and_efficiency(
                df, adapter, engine_id, flight
            )
            if early is not None:
                return early

            # 3) choose mass strategy + compute perf (now returns q_fuel_used)
            perf, q_fuel_used = self._choose_mass_strategy(
                adapter, df, flight, icao, q_fuel_attr, self.params.reference_q_fuel
            )

            # 4) finalize df columns, compute efficiency if needed (using q_fuel_used)
            self._finalize_columns(df, perf)
            self._compute_engine_efficiency_if_missing(df, perf, q_fuel_used)

            # 5) build Flight output
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
    ) -> tuple[str, str | None, str | None, float | None]:
        """Extract required aircraft attributes from flight.attrs."""
        icao: str | None = (
            flight.attrs.get("aircraft_type") if hasattr(flight, "attrs") else None
        )
        if not icao:
            raise KeyError("Flight attrs missing 'aircraft_type'")

        series: str | None = (
            flight.attrs.get("aircraft_series") if hasattr(flight, "attrs") else None
        )

        engine_id: str | None = (
            flight.attrs.get("engine_uid") if hasattr(flight, "attrs") else None
        )
        q_fuel: float | None = flight.fuel.q_fuel

        return icao, series, engine_id, q_fuel

    def _resolve_bada_adapter(
        self,
        icao: str,
        series: str | None,
        engine_id: str | None,
        force_bada3: bool = False,
    ) -> tuple[BaseBADAAdapter, str, int, str]:
        """Resolve BADA adapter based on aircraft type and available info."""
        nb_eng, bada3_code, bada4_code, resolved_engine = self.params.bada_type(
            icao, series=series, engine_id=engine_id
        )
        bada4_code = _normalize_code_or_none(bada4_code)

        if bada4_code is None or force_bada3:
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
        """Compute required kinematic columns for performance calculation."""
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

    def _compute_ground_and_true_airspeed(
        self, flight: Flight, window: int
    ) -> pd.DataFrame:
        """Compute ground speed and true airspeed columns."""
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
        """Compute kinematic columns: rocd, acceleration, segment_duration."""
        df["segment_duration"] = flight.segment_duration()
        df["rocd"] = flight.segment_rocd()
        df["segment_duration"] = pd.to_numeric(df["segment_duration"], errors="coerce")

        tas: NDArray[np.floating] = df["true_airspeed"].to_numpy(
            dtype=float, copy=False
        )
        dt: NDArray[np.floating] = df["segment_duration"].to_numpy(
            dtype=float, copy=False
        )
        df["acceleration"] = pc_acceleration(tas, dt)

    def _compute_delta_tau(
        self,
        df: pd.DataFrame,
        method: Literal["point", "zero"],
        fill: Literal["bffill", "zero", "none"],
    ) -> None:
        """Compute delta-tau (air temperature deviation from ISA)."""
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
    ) -> FlightWithPerformance | None:
        """If AO provided fuel_flow and engine_efficiency, skip BADA model."""
        if "fuel_flow" in df.columns and "engine_efficiency" in df.columns:
            self.logger.debug(
                "Flight already has 'fuel_flow' and 'engine_efficiency', skipping BADA model",
                extra={"rows": len(df)},
            )
            df["fuel_burn"] = df["fuel_flow"] * df["segment_duration"]

            if "fuel" not in df.columns and "fuel_burn" in df.columns:
                df["fuel"] = df["fuel_burn"]

            out = Flight(data=df, attrs={**flight.attrs}, fuel=flight.fuel)
            out.attrs["engine_uid"] = engine_id
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
        q_fuel_attr: float | None,
        reference_q_fuel: float,
    ) -> tuple[PerfOutput, float]:
        """Choose mass estimation strategy and use iterative estimation with the performance
        model if needed. Returns both perf output and q_fuel_used."""

        # Determine q_fuel to use
        q_fuel_used = q_fuel_attr if q_fuel_attr is not None else reference_q_fuel

        if q_fuel_attr is not None:
            self.logger.debug(
                "'q_fuel' attribute provided (%s J/kg), using it instead of default %s J/kg",
                q_fuel_attr,
                reference_q_fuel,
            )

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
            perf = self._single_pass_performance(
                adapter,
                df,
                initial_mass=None,
                q_fuel_used=q_fuel_used,
                default_q_fuel=reference_q_fuel,
            )
            return perf, q_fuel_used

        initial_mass: float | None = flight.attrs.get("takeoff_weight")
        if initial_mass is not None:
            self.logger.debug("'takeoff_weight' attribute provided, using it")
            perf = self._single_pass_performance(
                adapter,
                df,
                initial_mass=initial_mass,
                q_fuel_used=q_fuel_used,
                default_q_fuel=reference_q_fuel,
            )
            return perf, q_fuel_used

        # iterative estimation
        perf = self._estimate_initial_mass_iterative(
            adapter, df, flight, icao, q_fuel_used, reference_q_fuel
        )
        return perf, q_fuel_used

    def _single_pass_performance(
        self,
        adapter: BaseBADAAdapter,
        df: pd.DataFrame,
        initial_mass: float | None,
        q_fuel_used: float,
        default_q_fuel: float,
    ) -> PerfOutput:
        """Single pass performance calculation with given or initial mass.
        Now applies q_fuel correction during calculation."""

        if initial_mass is None and "aircraft_mass" not in df.columns:
            raise PerformanceStepError(
                "Initial mass not provided and 'aircraft_mass' column missing"
            )
        if initial_mass is not None and "aircraft_mass" in df.columns:
            self.logger.warning(
                "Both initial mass and 'aircraft_mass' column provided; ignoring initial mass"
            )
            initial_mass = None

        # Calculate correction ratio
        q_fuel_ratio = q_fuel_used / default_q_fuel

        mass_arr: list[float] = []
        ff_arr: list[float] = []
        thrust_arr: list[float] = []
        phase_arr: list[FlightPhase] = []
        segment_arr: list[str] = []

        mass_curr = initial_mass

        for pt in df.itertuples(index=False, name="FlightPt"):
            pt_mass = (
                mass_curr if mass_curr is not None else _as_float(pt.aircraft_mass)
            )

            ff, thrust, phase, thrust_seg = adapter.thrust_fuel_segment(
                pt_mass,
                _as_float(pt.altitude),
                _as_float(pt.true_airspeed),
                ft_to_m(_as_float(pt.rocd))
                / 60,  # Convert ft/min to m/s. The adapter requires SI
                _as_float(pt.acceleration),
                _as_float(pt.delta_tau),
            )

            # Apply q_fuel correction immediately
            ff_corrected = _as_float(ff) / q_fuel_ratio

            mass_arr.append(pt_mass)
            ff_arr.append(ff_corrected)
            thrust_arr.append(_as_float(thrust))
            phase_arr.append(phase)
            segment_arr.append(str(thrust_seg))

            if mass_curr is not None:
                mass_curr -= ff_corrected * _as_float(pt.segment_duration)

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
        q_fuel_used: float,
        default_q_fuel: float,
    ) -> PerfOutput:
        """Iterative initial mass estimation using BADA performance model."""

        payload_factor: float | None = flight.attrs.get("payload_factor")

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
                "BADA adapter for ICAO '%s' does not provide MPL, assuming MPL = MTOW - OEW. Conservative case", # noqa: E501
                icao,
            )
            maximum_payload = maximum_takeoff_weight - operating_empty_weight
        else:
            maximum_payload = adapter.MPL

        zero_fuel_weight: float = (
            operating_empty_weight + payload_factor * maximum_payload
        )
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
            q_fuel_used=q_fuel_used,
            default_q_fuel=default_q_fuel,
        )
        fuel_consumed = float(
            (np.asarray(perf["fuel_flow"]) * df["segment_duration"]).sum()
        )
        fuel_onboard = fuel_consumed * fuel_factor
        initial_mass = min(maximum_takeoff_weight, zero_fuel_weight + fuel_onboard)

        self.logger.debug(
            "Initial mass estimate: %s kg. MTOW: %s kg",
            initial_mass,
            maximum_takeoff_weight,
        )

        rel_mass_diff = float("inf")
        iter_count = 1

        while (
            rel_mass_diff > self.params.max_rel_mass_diff
            and iter_count < self.params.max_mass_estimation_iter
        ):
            prev_mass = initial_mass

            perf = self._single_pass_performance(
                adapter,
                df,
                initial_mass=initial_mass,
                q_fuel_used=q_fuel_used,
                default_q_fuel=default_q_fuel,
            )
            fuel_consumed = float(
                (np.asarray(perf["fuel_flow"]) * df["segment_duration"]).sum()
            )
            fuel_onboard = fuel_consumed * fuel_factor
            initial_mass = min(maximum_takeoff_weight, zero_fuel_weight + fuel_onboard)

            rel_mass_diff = abs(prev_mass - initial_mass) / prev_mass

            self.logger.debug(
                "Mass estimation iteration %s: %s kg (diff %.2f%%)",
                iter_count,
                initial_mass,
                rel_mass_diff * 100,
            )
            iter_count += 1

        return perf

    # ---------- post-processing ----------
    def _compute_engine_efficiency_if_missing(
        self,
        df: pd.DataFrame,
        perf: PerfOutput,
        q_fuel_used: float,
    ) -> None:
        """Compute engine_efficiency column if missing in flight.
        Now uses the correct q_fuel_used value."""

        if "engine_efficiency" in df.columns:
            self.logger.debug("'engine_efficiency' column already provided, keeping it")
            return

        tas: NDArray[np.floating] = df["true_airspeed"].to_numpy(
            dtype=float, copy=False
        )
        thrust: NDArray[np.floating] = np.asarray(perf["thrust"], dtype=float)
        ff: NDArray[np.floating] = np.asarray(perf["fuel_flow"], dtype=float)

        df["engine_efficiency"] = overall_propulsion_efficiency(
            tas,
            thrust,
            ff,
            q_fuel_used,  # Use the corrected q_fuel value
            is_descent=False,
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
        out.attrs["engine_uid"] = engine_id
