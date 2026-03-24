"""
BADA Performance Model Module

Implements aircraft performance calculations using EUROCONTROL's Base of Aircraft Data (BADA) models.

Features
--------
- Thrust and fuel flow calculation
- Aircraft mass estimation
- Flight phase detection
- Engine efficiency computation
- Aircraft-specific parameter lookups
- BADA3 and BADA4 model support with automatic selection and fallback
- Iterative mass estimation for unknown initial mass
- Flexible engine efficiency computation
- Multiple delta-tau computation methods
- True airspeed smoothing
- Comprehensive error handling

Classes
-------
BADAPerformanceModel
     Main step for BADA-based performance computation.
BADAPerformanceModelParams
     Parameters for the BADA performance model calculation.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any
from typing import Literal
from typing import TypedDict

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from pycontrails import Flight
from pycontrails.physics.jet import acceleration as pc_acceleration
from pycontrails.physics.jet import overall_propulsion_efficiency
from pycontrails.physics.units import ft_to_m
from pycontrails.physics.units import m_to_T_isa

from pyneats.core.neats_default_parameters import DEFAULT_BADA3_VERSION
from pyneats.core.neats_default_parameters import DEFAULT_BADA4_VERSION
from pyneats.core.neats_default_parameters import DEFAULT_BADA_MAX_CONSECUTIVE_FAILURES
from pyneats.core.neats_default_parameters import DEFAULT_DELTA_TAU_COMPUTE_METHOD
from pyneats.core.neats_default_parameters import DEFAULT_DELTA_TAU_FILL_METHOD
from pyneats.core.neats_default_parameters import DEFAULT_FF_OUTLIER_THRESHOLD
from pyneats.core.neats_default_parameters import DEFAULT_FUEL_BURN_THRESHOLD
from pyneats.core.neats_default_parameters import DEFAULT_FUEL_RESERVE_FRACTION
from pyneats.core.neats_default_parameters import DEFAULT_MAX_MASS_ESTIMATION_ITER
from pyneats.core.neats_default_parameters import DEFAULT_MAX_REL_MASS_DIFF
from pyneats.core.neats_default_parameters import DEFAULT_MIN_ALTITUDE_FL
from pyneats.core.neats_default_parameters import DEFAULT_PAYLOAD_FACTOR
from pyneats.core.neats_default_parameters import DEFAULT_ROCD_PHASE_THRESHOLD
from pyneats.core.neats_default_parameters import (
    DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW,
)
from pyneats.core.neats_default_parameters import REFERENCE_Q_FUEL
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.performance.altitude_filter import filter_low_altitude_points
from pyneats.steps.performance.bada_adapters import BADA3Adapter
from pyneats.steps.performance.bada_adapters import BADA4Adapter
from pyneats.steps.performance.bada_adapters import BaseBADAAdapter
from pyneats.steps.performance.bada_adapters import FlightPhase
from pyneats.steps.performance.bada_mapper import BadaMapper
from pyneats.steps.performance.bada_mapper import BadaMappingPaths
from pyneats.steps.performance.params import PerformanceModelParams
from pyneats.steps.performance.protocol import PerformanceModel
from pyneats.steps.performance.protocol import PerformanceStepError
from pyneats.steps.performance.speed_filter import filter_low_speed_points
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
    """
    Output of performance calculation step.

    Attributes
    ----------
    mass : list of float
        Estimated aircraft mass at each trajectory point.
    fuel_flow : list of float
        Fuel flow at each trajectory point.
    thrust : list of float
        Thrust at each trajectory point.
    phase : list of FlightPhase
        Flight phase at each trajectory point.
    segment : list of str
        Segment label at each trajectory point.
    """

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
    """
    Parameters for the BADA performance model calculation.

    Attributes
    ----------
    true_air_speed_smoothing_window : int
        Window size for true airspeed smoothing.
    reference_q_fuel : float
        Reference fuel heat value.
    delta_tau_compute_method : {"point", "zero"}
        Method for delta-tau computation.
    delta_tau_fill_method : {"bffill", "none", "zero"}
        Method for filling delta-tau values.
    bada4_version : str
        Version of BADA4 to use.
    bada3_version : str
        Version of BADA3 to use.
    bada4_root_path : str
        Root path for BADA4 data.
    bada3_root_path : str
        Root path for BADA3 data.
    payload_factor : float
        Payload factor for mass estimation.
    fuel_reserve_fraction : float
        Fuel reserve fraction for mass estimation.
    max_rel_mass_diff : float
        Maximum relative mass difference for convergence.
    max_mass_estimation_iter : int
        Maximum number of mass estimation iterations.
    rocd_phase_threshold : float
        Threshold for rate of climb/descent phase detection.
    """

    true_air_speed_smoothing_window: int = DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW
    reference_q_fuel: float = REFERENCE_Q_FUEL

    delta_tau_compute_method: Literal["point", "zero"] = (
        DEFAULT_DELTA_TAU_COMPUTE_METHOD
    )
    delta_tau_fill_method: Literal["bffill", "none", "zero"] = (
        DEFAULT_DELTA_TAU_FILL_METHOD
    )

    max_consecutive_failures = DEFAULT_BADA_MAX_CONSECUTIVE_FAILURES
    ff_outlier_threshold = DEFAULT_FF_OUTLIER_THRESHOLD

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
    fuel_burn_threshold: float = DEFAULT_FUEL_BURN_THRESHOLD

    def bada_type(
        self,
        icao: str,
        series: str | None,
        engine_id: str | None,
    ) -> tuple[int, str, str, str]:
        """Resolve BADA type using the mapper"""

        return self.mapper.bada_type(icao, series, engine_id)


@register(PerformanceModel, "bada")  # type: ignore[type-abstract]
class BADAPerformanceModel(
    BaseStep[
        FlightWithWeather,
        FlightWithPerformance,
        BADAPerformanceModelParams,
    ]
):
    """
    Step for BADA-based aircraft performance computation.

    Wraps BADA adapters and provides a testable structure for performance calculation.

    Methods
    -------
    run(flight)
        Run BADA performance model on the given flight data.
    run_by_bada_version(...)
        Run BADA performance model with optional BADA3 enforcement.
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
                f"BADA4 path '{self.bada4_path}' does not exist or is not a directory",
                retryable=False,
            )

        if not self.bada3_path.exists() or not self.bada3_path.is_dir():
            raise PerformanceStepError(
                f"BADA3 path '{self.bada3_path}' does not exist or is not a directory",
                retryable=False,
            )

    # ---------- public API ----------
    def run(self, flight: FlightWithWeather) -> FlightWithPerformance:
        """Run BADA performance model on the given flight data.

        Fallback chain:
            1. Normal BADA (4 or 3) execution (with speed filter applied)
            2. Retry with BADA3 forced (if first attempt used BADA4)
            3. Altitude fallback — filter points below FL15, retry
        """

        # --- Preprocessing + aircraft data extraction ---
        try:
            df = self._preprocess(flight)
            icao, series, engine_id_attr, q_fuel_attr = self._extract_aircraft_attrs(
                flight
            )

        except Exception as e:
            self.logger.info(
                "Preprocessing and aircraft attribute extraction failed during Performance evaluation"
            )

            raise PerformanceStepError(
                f"Preprocessing and aircraft attribute extraction failed during Performance evaluation: {e}",
                retryable=False,
            ) from e

        # --- First attempt: normal BADA (3 or 4) execution ---
        try:
            return self.run_by_bada_version(
                flight, df, icao, series, engine_id_attr, q_fuel_attr
            )

        except PerformanceStepError as exc:
            self.logger.info(
                "BADA performance evaluation failed. Retrying BADA performance evaluation with BADA3 enforced",
                extra={"icao": icao, "series": series, "engine_id": engine_id_attr},
            )

            # --- Second attempt: retry with BADA3 ---
            try:
                _, _, bada4_code, _ = self.params.bada_type(
                    icao, series=series, engine_id=engine_id_attr
                )
                bada4_code = _normalize_code_or_none(bada4_code)

                if bada4_code is None:
                    self.logger.info(
                        "BADA performance evaluation already performed with BADA3, no need to retry with BADA3 again",
                        extra={
                            "icao": icao,
                            "series": series,
                            "engine_id": engine_id_attr,
                        },
                    )
                    raise PerformanceStepError(
                        "BADA performance evaluation already performed with BADA3, no need to retry with BADA3 again"
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

            except PerformanceStepError as exc2:
                # --- Third attempt: altitude fallback ---
                if not exc2.retryable:
                    raise

                return self._run_with_altitude_fallback(
                    flight, icao, series, engine_id_attr, q_fuel_attr, exc2
                )

    def _run_with_altitude_fallback(
        self,
        flight: FlightWithWeather,
        icao: str,
        series: str | None,
        engine_id_attr: str | None,
        q_fuel_attr: float | None,
        original_exc: PerformanceStepError,
    ) -> FlightWithPerformance:
        """Filter low-altitude points and retry performance evaluation.

        Mirrors the BADA4 → BADA3 chain on the filtered data, since the
        pre-filter parser allowed both versions to run on clean data.
        """
        self.logger.info(
            "Attempting altitude fallback: filtering points below FL%s",
            DEFAULT_MIN_ALTITUDE_FL,
            extra={"icao": icao, "series": series, "engine_id": engine_id_attr},
        )

        try:
            filtered_flight = filter_low_altitude_points(flight)
        except PerformanceStepError:
            # Cannot filter (no low points, or too many filtered) — propagate original
            raise original_exc from original_exc.__cause__

        try:
            df_filtered = self._preprocess(filtered_flight)

            # Try default BADA version on filtered data
            try:
                return self.run_by_bada_version(
                    filtered_flight,
                    df_filtered,
                    icao,
                    series,
                    engine_id_attr,
                    q_fuel_attr,
                )
            except PerformanceStepError:
                # Try BADA3 on filtered data
                return self.run_by_bada_version(
                    filtered_flight,
                    df_filtered,
                    icao,
                    series,
                    engine_id_attr,
                    q_fuel_attr,
                    force_bada3=True,
                )

        except PerformanceStepError as exc3:
            self.logger.info(
                "Altitude fallback also failed",
                extra={"icao": icao, "error": str(exc3)},
            )
            raise PerformanceStepError(
                f"Performance evaluation failed after altitude fallback "
                f"(underlying error: {exc3})"
            ) from exc3

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
        """Run BADA performance model on the given flight data, with optional BADA3 enforcement.

        After resolving the BADA adapter, a speed filter removes trajectory
        points with TAS below VStall.  If the filter fails for any reason
        (no slow points, too many filtered, missing MTOW), the pipeline
        degrades gracefully and proceeds with the original unfiltered data.
        """

        try:
            # 1) resolve adapter + core attrs
            adapter, bada_version, nb_eng, engine_id = self._resolve_bada_adapter(
                icao, series, engine_id_attr, force_bada3
            )

            # 1b) speed filter — remove low-TAS points before perf computation
            try:
                flight = filter_low_speed_points(flight, adapter)
            except Exception:
                self.logger.warning(
                    "Speed filter failed — proceeding with unfiltered data",
                    extra={"icao": icao},
                )

            # 2) early exit if AO provided fuel_flow & engine_efficiency
            early = self._early_exit_if_fuel_and_efficiency(
                df, adapter, engine_id, flight
            )
            if early is not None:
                return early

            # 3) derive fuel_flow from mass trajectory if needed
            self._derive_fuel_flow_from_mass_if_needed(df)

            # 4) choose mass strategy + compute perf (now returns q_fuel_used)
            perf, q_fuel_used = self._choose_mass_strategy(
                adapter, df, flight, icao, q_fuel_attr, self.params.reference_q_fuel
            )

            # 5) finalize df columns, compute efficiency if needed (using q_fuel_used)
            self._finalize_columns(df, perf)

            # 6) build result (guardrail, efficiency, output)
            return self._build_result(
                df,
                flight,
                adapter,
                bada_version,
                nb_eng,
                engine_id,
                icao,
                perf,
                q_fuel_used,
            )

        except PerformanceStepError:
            raise
        except Exception as e:  # pylint: disable=broad-except
            self.logger.exception("Performance evaluation failed")
            raise PerformanceStepError(f"Performance evaluation failed: {e}") from e

    def _build_result(
        self,
        df: pd.DataFrame,
        flight: FlightWithWeather,
        adapter: BaseBADAAdapter,
        bada_version: str,
        nb_eng: int,
        engine_id: str | None,
        icao: str,
        perf: object,
        q_fuel_used: float,
    ) -> FlightWithPerformance:
        """Apply guardrails, compute efficiency, and build the output flight."""
        # Fuel burn guardrail: reject if total fuel > (MTOW - OEW) * threshold
        if adapter.MTOW is not None and adapter.OEW is not None:
            useful_payload = adapter.MTOW - adapter.OEW
            total_fuel = float(df["fuel_burn"].sum())
            limit = useful_payload * self.params.fuel_burn_threshold
            if total_fuel > limit:
                raise PerformanceStepError(
                    f"Total fuel burn {total_fuel:.0f} kg exceeds "
                    f"useful payload capacity {useful_payload:.0f} kg x "
                    f"{self.params.fuel_burn_threshold} = {limit:.0f} kg",
                    retryable=False,
                )
        else:
            self.logger.warning(
                "MTOW or OEW unavailable — skipping fuel burn guardrail"
            )

        self._compute_engine_efficiency_if_missing(df, perf, q_fuel_used)

        out = Flight(data=df, attrs={**flight.attrs}, fuel=flight.fuel)
        self._attach_output_attrs(out, adapter, bada_version, nb_eng, engine_id)

        out_view = FlightWithPerformance.from_flight(out)

        self.logger.info(
            "Performance step completed",
            extra={"rows": len(df), "icao": icao, "bada": bada_version},
        )
        return out_view

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

        if "true_airspeed" not in df.columns:
            u: NDArray[np.floating] = df["u_wind"].to_numpy(dtype=float, copy=False)
            v: NDArray[np.floating] = df["v_wind"].to_numpy(dtype=float, copy=False)
            df["true_airspeed"] = flight.segment_true_airspeed(
                u_wind=u,
                v_wind=v,
                smooth=True,
                window_length=window,
                polyorder=1,
            )
        else:
            self.logger.debug("'true_airspeed' column already provided, keeping it")

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
        """If AO provided fuel_flow, engine_efficiency, and aircraft_mass, skip BADA model."""
        if (
            "fuel_flow" in df.columns
            and "engine_efficiency" in df.columns
            and "aircraft_mass" in df.columns
        ):
            self.logger.debug(
                "Flight already has 'fuel_flow', 'engine_efficiency', and 'aircraft_mass', skipping BADA model",
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

    def _derive_fuel_flow_from_mass_if_needed(self, df: pd.DataFrame) -> None:
        """
        Derive fuel_flow from aircraft_mass trajectory if mass provided but fuel_flow not.

        When airlines provide aircraft_mass along the trajectory, we can infer fuel consumption
        from the decrease in mass over time:
            fuel_flow[i] = -(mass[i+1] - mass[i]) / segment_duration[i]

        where segment_duration[i] is in seconds, and fuel_flow is in kg/s.

        The derived fuel_flow will be preserved in the output (like airline-provided fuel_flow),
        while engine efficiency will still be computed using BADA thrust and fuel_flow for
        internal consistency with the physics model.
        """
        if "aircraft_mass" not in df.columns or "fuel_flow" in df.columns:
            return

        self.logger.info("Deriving fuel_flow from aircraft_mass trajectory decrease")

        # Ensure numeric types
        df["aircraft_mass"] = pd.to_numeric(df["aircraft_mass"], errors="coerce")
        df["segment_duration"] = pd.to_numeric(df["segment_duration"], errors="coerce")

        # Derive fuel_flow from mass differences
        # segment_duration[i] is in seconds (from flight.segment_duration())
        mass_vals = df["aircraft_mass"].values
        dt_vals = df["segment_duration"].values

        # fuel_flow[i] = -(mass[i+1] - mass[i]) / segment_duration[i]
        # Use prepend to handle first waypoint (assumes no mass change at t=0)
        mass_diff = np.diff(mass_vals, prepend=mass_vals[0])  # First segment: diff=0
        fuel_flow_derived = -mass_diff / dt_vals  # Negative sign because mass decreases

        # Ensure non-negative (handle numerical errors or unusual cases)
        fuel_flow_derived = np.maximum(fuel_flow_derived, 0.0)

        df["fuel_flow"] = fuel_flow_derived

        self.logger.debug(
            "Derived fuel_flow from mass trajectory",
            extra={
                "mean_ff_kg_s": float(fuel_flow_derived.mean()),
                "total_fuel_kg": float((fuel_flow_derived * dt_vals).sum()),
            },
        )

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
                "Initial mass not provided and 'aircraft_mass' column missing",
                retryable=False,
            )
        if initial_mass is not None and "aircraft_mass" in df.columns:
            self.logger.warning(
                "Both initial mass and 'aircraft_mass' column provided; ignoring initial mass"
            )
            initial_mass = None

        max_consecutive_failures = self.params.max_consecutive_failures
        ff_outlier_threshold = self.params.ff_outlier_threshold

        # Calculate correction ratio
        q_fuel_ratio = q_fuel_used / default_q_fuel

        mass_arr: list[float] = []
        ff_arr: list[float] = []
        thrust_arr: list[float] = []
        phase_arr: list[FlightPhase] = []
        segment_arr: list[str] = []

        mass_curr = initial_mass

        # Trackers for error propagation
        consecutive_failures = 0
        prev_ff_corrected = None
        prev_thrust = None
        prev_phase = None
        prev_segment = None

        for pt in df.itertuples(index=False, name="FlightPt"):
            pt_mass = (
                mass_curr if mass_curr is not None else _as_float(pt.aircraft_mass)
            )

            try:
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
                thrust_val = _as_float(thrust)
                phase_val = phase
                segment_val = str(thrust_seg)

                if (ff_corrected > ff_outlier_threshold) or (ff_corrected < 0.0):
                    raise Exception("BADA fuel flow is unrealistic")

                # If successful, reset the failure counter and update our "last known good" values
                consecutive_failures = 0
                prev_ff_corrected = ff_corrected
                prev_thrust = thrust_val
                prev_phase = phase_val
                prev_segment = segment_val

            except Exception as e:
                # Edge case: If the very first point fails, we have no previous state to propagate.
                if prev_ff_corrected is None:
                    raise PerformanceStepError(
                        f"BADA calculation failed on the very first trajectory point: {e}"
                    ) from e

                consecutive_failures += 1

                # If we exceed the threshold, raise the exception for the whole flight
                if consecutive_failures > max_consecutive_failures:
                    raise PerformanceStepError(
                        f"Exceeded maximum consecutive BADA failures ({max_consecutive_failures}). "
                        f"Last error: {e}"
                    ) from e

                # Log the interpolation to keep a trace of the correction (optional but recommended)
                self.logger.debug(
                    "BADA computation failed at altitude %s. Propagating previous values. (Failure %s/%s)",
                    pt.altitude,
                    consecutive_failures,
                    max_consecutive_failures,
                )

                # Propagate from the last successful state
                ff_corrected = prev_ff_corrected
                thrust_val = prev_thrust
                phase_val = prev_phase
                segment_val = prev_segment

            mass_arr.append(pt_mass)
            ff_arr.append(ff_corrected)
            thrust_arr.append(thrust_val)
            phase_arr.append(phase_val)
            segment_arr.append(segment_val)

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
                f"BADA adapter for ICAO '{icao}' does not provide OEW or MTOW",
                retryable=False,
            )

        if adapter.MPL is None:
            self.logger.warning(
                "BADA adapter for ICAO '%s' does not provide MPL, assuming MPL = MTOW - OEW. Conservative case",
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
