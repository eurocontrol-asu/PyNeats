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
- Untrusted true airspeeds replaced (no row removed)
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
from typing import NamedTuple
from typing import TypedDict

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from pycontrails import Flight
from pycontrails.physics.jet import acceleration as pc_acceleration
from pycontrails.physics.jet import overall_propulsion_efficiency
from pycontrails.physics.units import ft_to_m
from pycontrails.physics.units import m_to_T_isa

from pyneats.core.neats_default_parameters import DEFAULT_AIRSPEED_STALL_CONFIG
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
    DEFAULT_TRUE_AIR_SPEED_SMOOTHING_POLYORDER,
)
from pyneats.core.neats_default_parameters import (
    DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW,
)
from pyneats.core.neats_default_parameters import REFERENCE_Q_FUEL
from pyneats.core.steps import BaseStep
from pyneats.core.steps_registry import register
from pyneats.steps.performance.airspeed_trust import apply_airspeed_trust
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


def _has_ao_fuel_and_efficiency(df: pd.DataFrame) -> bool:
    """True when ``df`` has ``fuel_flow``, ``engine_efficiency`` and ``aircraft_mass``.

    The condition of ``BADAPerformanceModel._early_exit_if_fuel_and_efficiency``:
    the AO provides the three (columns left entirely empty are dropped at
    parsing), and the BADA fuel flow is not computed. It is evaluated before
    the airspeed trust step, which adds no column, and before
    ``_derive_fuel_flow_from_mass_if_needed`` adds a ``fuel_flow`` column.
    """
    return (
        "fuel_flow" in df.columns
        and "engine_efficiency" in df.columns
        and "aircraft_mass" in df.columns
    )


def _has_ao_fuel_flow_without_mass(df: pd.DataFrame) -> bool:
    """True when the AO provides ``fuel_flow`` but no ``aircraft_mass`` column.

    On this path the mass is integrated from the AO fuel flow (audit A13,
    ``BADAPerformanceModel._performance_from_ao_fuel_flow``). Evaluated after
    the early exit and before ``_derive_fuel_flow_from_mass_if_needed``, which
    adds ``fuel_flow`` only when ``aircraft_mass`` is present.
    """
    return "fuel_flow" in df.columns and "aircraft_mass" not in df.columns


def _fuel_burn_per_segment(
    fuel_flow: NDArray[np.floating], segment_duration: NDArray[np.floating]
) -> NDArray[np.floating]:
    """Fuel burned over each forward segment [kg] = fuel_flow [kg/s] x duration [s].

    A segment where the product is not finite (empty fuel flow, or the NaN
    duration of the last point) counts as 0 kg, as the sum of ``fuel_burn``
    (pandas skips NaN) does for the reported fuel.
    """
    burn = np.asarray(fuel_flow, dtype=float) * np.asarray(
        segment_duration, dtype=float
    )
    return np.where(np.isfinite(burn), burn, 0.0)


def _mass_from_fuel_flow(
    initial_mass: float,
    fuel_flow: NDArray[np.floating],
    segment_duration: NDArray[np.floating],
) -> NDArray[np.floating]:
    """Aircraft mass [kg] at each point, decreasing with the given fuel flow.

    mass[0] = initial_mass and mass[i + 1] = mass[i] - fuel_flow[i] [kg/s] x
    segment_duration[i] [s], with segment_duration[i] = t[i + 1] - t[i]. The
    burn of the last point (no next point) is not applied, so
    mass[0] - mass[-1] equals the sum of ``fuel_burn`` (NaN skipped). A
    segment with a non-finite burn counts as 0 kg (``_fuel_burn_per_segment``).
    The result is not clipped.
    """
    burn = _fuel_burn_per_segment(fuel_flow, segment_duration)
    burned_before = np.concatenate(([0.0], np.cumsum(burn)[:-1]))
    return float(initial_mass) - burned_before


# Hint added to a fuel-burn guardrail rejection of an AO fuel flow.
_AO_FUEL_FLOW_HINT = (
    " (fuel flow provided by the aircraft operator: it must be"
    " in kg/s for the whole aircraft; kg/h gives 3600 times"
    " too much)"
)


class _ZeroFuelWeight(NamedTuple):
    """Masses [kg] for the initial mass estimate (payload_factor dimensionless)."""

    operating_empty_weight: float
    maximum_takeoff_weight: float
    payload_factor: float
    zero_fuel_weight: float


def _zero_fuel_weight(
    adapter: BaseBADAAdapter,
    flight: Flight,
    icao: str,
    default_payload_factor: float,
    logger: Any,
) -> _ZeroFuelWeight:
    """ZFW = OEW + payload_factor x MPL [kg] for the initial mass estimate.

    ``payload_factor`` is the flight attribute, or ``default_payload_factor``
    when the attribute is missing or not finite (a warning is logged then).
    MPL is taken as MTOW - OEW when the adapter gives no usable MPL (missing,
    zero, negative or NaN). Fails without retry when the adapter gives no OEW
    or MTOW.
    """
    payload_factor: float | None = flight.attrs.get("payload_factor")

    if payload_factor is None:
        payload_factor = default_payload_factor
    elif not np.isfinite(payload_factor):
        # NaN would otherwise pass min(MTOW, NaN) as MTOW without a word.
        logger.warning(
            "Flight %s: 'payload_factor' attribute %r is not finite;"
            " using the default %s",
            flight.attrs.get("flight_id"),
            payload_factor,
            default_payload_factor,
        )
        payload_factor = default_payload_factor
    else:
        logger.debug("'payload_factor' attribute provided, using it")

    operating_empty_weight = adapter.OEW
    maximum_takeoff_weight = adapter.MTOW
    if operating_empty_weight is None or maximum_takeoff_weight is None:
        raise PerformanceStepError(
            f"BADA adapter for ICAO '{icao}' does not provide OEW or MTOW",
            retryable=False,
        )

    # A zero, negative or NaN MPL is treated as missing (BADA 3.16 U2____.OPF
    # gives 0, which would otherwise mean ZFW = OEW whatever the payload factor).
    bada_mpl = adapter.MPL
    if bada_mpl is None or not np.isfinite(bada_mpl) or bada_mpl <= 0:
        logger.warning(
            "BADA adapter for ICAO '%s' does not provide a usable MPL (%s), assuming MPL = MTOW - OEW. Conservative case",
            icao,
            bada_mpl,
        )
        maximum_payload = maximum_takeoff_weight - operating_empty_weight
    else:
        maximum_payload = bada_mpl

    return _ZeroFuelWeight(
        operating_empty_weight=operating_empty_weight,
        maximum_takeoff_weight=maximum_takeoff_weight,
        payload_factor=payload_factor,
        zero_fuel_weight=operating_empty_weight + payload_factor * maximum_payload,
    )


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
        Savitzky-Golay window length (number of points) passed to pycontrails
        ``segment_true_airspeed``; used only when TAS is computed from winds.
        The same smoothing is applied to the TAS of a flight whose untrusted
        airspeeds were replaced (see ``airspeed_stall_config``).
    airspeed_stall_config : {"TO", "LD"}
        BADA configuration of the stall speed used to trust a true airspeed:
        a row whose CAS [m/s] is below the BADA stall CAS at MTOW in this
        configuration ("TO" take-off, "LD" landing) is untrusted, as is a row
        whose TAS is not finite, whose CAS is above the BADA maximum operating
        speed VMO (400 kt when the BADA model has none) or whose Mach number
        is 1 or more.
        Untrusted TAS values are replaced by linear interpolation in time
        between trusted rows; no row is removed (see
        ``pyneats.steps.performance.airspeed_trust``).
    reference_q_fuel : float
        Lower calorific value [J/kg of fuel] of the fuel BADA assumes. BADA
        fuel flow is divided by ``q_fuel_used / reference_q_fuel``. The default
        (``REFERENCE_Q_FUEL`` = 43.217e6 J/kg) is the BADA4 4.2.1 LHV, used for
        BADA4 and BADA3 (see docs/internal/pyneats_units_audit.md, A11/A12).
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
        Payload mass as a fraction of the BADA maximum payload (MPL):
        ZFW = OEW + payload_factor x MPL [kg], with MPL taken as MTOW - OEW
        when the adapter gives no usable MPL (missing, zero, negative or NaN;
        BADA3 and BADA4 adapters both read it from the BADA files).
        The first-pass constant-mass guess is
        OEW + payload_factor x (MTOW - OEW). Not a seat load factor; this
        parameter is not range-checked. Overridden by the ``payload_factor``
        flight attribute (limited to 0-1 by ``NeatsTrajectoryParser``: above
        1 set to 1.0, negative rejected) and used only when neither an
        ``aircraft_mass`` column nor a ``takeoff_weight`` attribute is given.
    fuel_reserve_fraction : float
        Dimensionless fraction: fuel on board = trip fuel x
        (1 + fuel_reserve_fraction) in the initial mass estimate.
    max_rel_mass_diff : float
        Convergence threshold on the relative change of the initial mass
        between iterations (dimensionless fraction).
    max_mass_estimation_iter : int
        Maximum number of mass estimation iterations.
    rocd_phase_threshold : float
        Rate of climb/descent threshold for phase detection [ft/min]; the
        adapters convert it to m/s.
    fuel_burn_threshold : float
        Guardrail: the flight is rejected when total fuel burn [kg] exceeds
        fuel_burn_threshold x (MTOW - OEW) [kg] (dimensionless multiple).

    Notes
    -----
    ``ff_outlier_threshold`` [kg/s, whole aircraft] is an upper bound checked
    only against the BADA-computed (q_fuel-corrected) fuel flow, never against
    a provided ``fuel_flow`` column.
    """

    true_air_speed_smoothing_window: int = DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW
    airspeed_stall_config: Literal["TO", "LD"] = DEFAULT_AIRSPEED_STALL_CONFIG
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
            1. Normal BADA (4 or 3) execution (after the airspeed trust step)
            2. Retry with BADA3 forced (if first attempt used BADA4)
            3. Altitude fallback — filter points below DEFAULT_MIN_ALTITUDE_FL
               (FL20 = 2000 ft = 609.6 m), retry

        A fuel-burn guardrail rejection goes through the whole chain: BADA3
        retry, then altitude fallback; the flight fails only if every attempt
        is rejected. The exception is a fuel flow provided by the AO (with
        engine efficiency and aircraft mass, or without aircraft mass), where
        the rejection is final: every retry would reuse the same operator fuel
        flow. A failure raised with ``retryable=False`` ends the chain
        where it occurs. On this path that flag is carried by the airspeed
        trust step (more than 80 % of the flight time untrusted or no trusted
        row, except when the AO provides fuel flow, engine efficiency and
        aircraft mass; or any error in the step) and by two internal
        consistency errors (a BADA file without MTOW or OEW when the take-off
        mass is estimated, and a missing initial mass), which do not occur
        with the BADA files in use.
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
            if not exc.retryable:
                raise

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
            except PerformanceStepError as exc4:
                # Try BADA3 on filtered data, unless the failure is final
                if not exc4.retryable:
                    raise
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

        After resolving the BADA adapter, the airspeed trust step replaces
        untrusted true airspeeds (not finite, CAS below the stall CAS of the
        adapter at MTOW, CAS above its VMO, or Mach >= 1) by linear
        interpolation in time; no row is removed (``apply_airspeed_trust``).
        It runs before every path, including the early exit when the AO
        provides fuel flow, engine efficiency and aircraft mass. The flight
        fails without retry (``retryable=False``) when the step raises, and
        when more than 80 % of its time is untrusted or no row is trusted,
        except on that early-exit path (``_has_ao_fuel_and_efficiency``),
        where the BADA fuel flow is not used: there the flight is kept, with
        its TAS replaced (kept as is when no row is trusted).
        """

        # Work on a copy: the steps below write columns (aircraft_mass, thrust,
        # fuel_flow, ...) into df. run() and the altitude fallback pass the same
        # df to a BADA3 retry, which would otherwise take those columns as AO data.
        df = df.copy()

        try:
            # 1) resolve adapter + core attrs
            adapter, bada_version, nb_eng, engine_id = self._resolve_bada_adapter(
                icao, series, engine_id_attr, force_bada3
            )

            # 1b) airspeed trust: untrusted TAS replaced by interpolation in
            # time; no row is removed, so segment_duration [s] and rocd stay
            # valid and acceleration is recomputed. Any failure here ends the
            # flight: no BADA3 retry, no altitude fallback. The 80 % rule does
            # not fail the early-exit path (AO fuel flow, efficiency and mass).
            try:
                df, _ = apply_airspeed_trust(
                    df,
                    adapter,
                    self._unsmoothed_true_airspeed(flight),
                    stall_config=self.params.airspeed_stall_config,
                    smoothing_window=self.params.true_air_speed_smoothing_window,
                    fail_when_mostly_untrusted=not _has_ao_fuel_and_efficiency(df),
                )
            except Exception as e:
                if isinstance(e, PerformanceStepError) and not e.retryable:
                    raise
                raise PerformanceStepError(
                    f"Airspeed trust step failed: {e}", retryable=False
                ) from e

            # 2) early exit if AO provided fuel_flow & engine_efficiency
            early = self._early_exit_if_fuel_and_efficiency(
                df, adapter, engine_id, flight
            )
            if early is not None:
                return early

            # 2b) AO fuel flow without AO mass: the mass will decrease with
            # this fuel flow (audit A13), so check it before integrating it.
            # A kg/h fuel flow would otherwise drive the mass negative inside
            # BADA. Final rejection: every retry reuses the same AO fuel flow.
            if _has_ao_fuel_flow_without_mass(df):
                self._check_ao_fuel_flow(df, adapter)

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
        # Retryable: the BADA3 retry and the altitude fallback (points below
        # FL20 removed) may still give a plausible result.
        self._check_total_fuel_burn(df, adapter)

        self._compute_engine_efficiency_if_missing(df, perf, q_fuel_used)

        out = Flight(data=df, attrs={**flight.attrs}, fuel=flight.fuel)
        self._attach_output_attrs(out, adapter, bada_version, nb_eng, engine_id)

        out_view = FlightWithPerformance.from_flight(out)

        self.logger.info(
            "Performance step completed",
            extra={"rows": len(df), "icao": icao, "bada": bada_version},
        )
        return out_view

    def _check_total_fuel_burn(
        self,
        df: pd.DataFrame,
        adapter: BaseBADAAdapter,
        *,
        retryable: bool = True,
        hint: str = "",
    ) -> None:
        """Fuel burn guardrail: reject if total fuel > (MTOW - OEW) x threshold.

        Total fuel burn in kg (pandas sum skips NaN); MTOW - OEW in kg. Skipped
        with a warning when MTOW or OEW is unavailable.
        """
        if adapter.MTOW is None or adapter.OEW is None:
            self.logger.warning(
                "MTOW or OEW unavailable — skipping fuel burn guardrail"
            )
            return
        useful_payload = adapter.MTOW - adapter.OEW
        total_fuel = float(df["fuel_burn"].sum())
        limit = useful_payload * self.params.fuel_burn_threshold
        if total_fuel > limit:
            raise PerformanceStepError(
                f"Total fuel burn {total_fuel:.0f} kg exceeds "
                f"useful payload capacity {useful_payload:.0f} kg x "
                f"{self.params.fuel_burn_threshold} = {limit:.0f} kg{hint}",
                retryable=retryable,
            )

    def _check_ao_fuel_flow(self, df: pd.DataFrame, adapter: BaseBADAAdapter) -> None:
        """Fuel-burn guardrail on the AO fuel flow, before any mass is integrated.

        Used when the AO provides ``fuel_flow`` without ``aircraft_mass``: the
        total of fuel_flow [kg/s] x segment_duration [s] (NaN skipped) is
        checked as in ``_check_total_fuel_burn``. The rejection is not
        retryable (a BADA3 retry or the altitude fallback would reuse the same
        AO fuel flow) and says the fuel flow must be in kg/s. ``df`` is not
        modified.
        """
        fuel_flow = pd.to_numeric(df["fuel_flow"], errors="coerce")
        self._check_total_fuel_burn(
            df.assign(fuel_burn=fuel_flow * df["segment_duration"]),
            adapter,
            retryable=False,
            hint=_AO_FUEL_FLOW_HINT,
        )

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
        # J/kg (LHV), already converted from the AO MJ/kg upstream; see the
        # NEATSFuel q_fuel docstring. Never None in practice: a pycontrails Fuel
        # always carries q_fuel (NEATSFuel default DEFAULT_Q_FUEL = 42.8e6 J/kg).
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
        """Compute ground speed and true airspeed columns [m/s].

        A provided ``true_airspeed`` column is used as is (m/s). Otherwise TAS
        is computed by pycontrails ``segment_true_airspeed`` from the ground
        speed (Savitzky-Golay smoothed over ``window`` points) and the
        ``u_wind``/``v_wind`` columns (m/s).
        """
        df = flight.dataframe.copy(deep=False)
        df["ground_speed"] = flight.segment_groundspeed()  # m/s

        if "true_airspeed" not in df.columns:
            u: NDArray[np.floating] = df["u_wind"].to_numpy(dtype=float, copy=False)
            v: NDArray[np.floating] = df["v_wind"].to_numpy(dtype=float, copy=False)
            df["true_airspeed"] = flight.segment_true_airspeed(
                u_wind=u,
                v_wind=v,
                smooth=True,
                window_length=window,
                polyorder=DEFAULT_TRUE_AIR_SPEED_SMOOTHING_POLYORDER,
            )
        else:
            # PyNEATS input unit: m/s. The AO JSON field `tas` is in knots.
            # The NEATS application converts knots to m/s (x 1852 / 3600) before
            # calling PyNEATS. Values received here must already be in m/s.
            self.logger.debug("'true_airspeed' column already provided, keeping it")

        # ensure numeric dtype early
        df["true_airspeed"] = pd.to_numeric(df["true_airspeed"], errors="coerce")
        return df

    def _unsmoothed_true_airspeed(self, flight: Flight) -> NDArray[np.floating] | None:
        """TAS [m/s] from the unsmoothed ground speed, or ``None`` if TAS is provided.

        pycontrails ``segment_true_airspeed`` with ``smooth=False`` and the same
        ``u_wind``/``v_wind`` columns [m/s] as ``_compute_ground_and_true_airspeed``
        (NaN at the last point, forward segment). The airspeed trust step
        decides trust and fills gaps on it.
        """
        if "true_airspeed" in flight:
            return None
        u: NDArray[np.floating] = np.asarray(flight["u_wind"], dtype=float)
        v: NDArray[np.floating] = np.asarray(flight["v_wind"], dtype=float)
        return flight.segment_true_airspeed(u_wind=u, v_wind=v, smooth=False)

    def _compute_kinematics(self, flight: Flight, df: pd.DataFrame) -> None:
        """Compute kinematic columns: rocd, acceleration, segment_duration.

        Forward differences: ``segment_duration`` [s] is t[i+1] - t[i] (NaN at
        the last point); ``rocd`` [ft/min] comes from pycontrails
        ``segment_rocd`` (converted to m/s at the adapter call);
        ``acceleration`` [m/s^2] is the TAS forward difference (0 at the last
        point, NaN replaced by 0).
        """
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
        """Compute delta-tau (air temperature deviation from ISA) [K].

        ``air_temperature`` [K] minus the ISA temperature at the ``altitude``
        column (pressure altitude, m). Passed to the adapters as pyBADA
        ``deltaTemp``.
        """
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
        """If AO provided fuel_flow, engine_efficiency, and aircraft_mass, skip BADA model.

        ``fuel_burn`` = fuel_flow [kg/s, treated as whole aircraft] x
        segment_duration [s], i.e. kg per forward segment. The fuel-burn
        guardrail applies (``_check_total_fuel_burn``); its rejection is not
        retryable, since a BADA3 retry or the altitude fallback would take
        this path again with the same operator fuel flow. A fuel flow sent in
        kg/h (3600 times too high) is caught this way. The point-by-point
        fuel-flow outlier check does not apply. Taken when
        ``_has_ao_fuel_and_efficiency(df)`` is True.
        """
        if _has_ao_fuel_and_efficiency(df):
            self.logger.debug(
                "Flight already has 'fuel_flow', 'engine_efficiency', and 'aircraft_mass', skipping BADA model",
                extra={"rows": len(df)},
            )
            df["fuel_burn"] = df["fuel_flow"] * df["segment_duration"]
            self._check_total_fuel_burn(
                df,
                adapter,
                retryable=False,
                hint=_AO_FUEL_FLOW_HINT,
            )

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
        from the decrease in mass over time. The code computes:
            fuel_flow[i] = (mass[i] - mass[i+1]) / segment_duration[i]

        i.e. the mass burned over segment i [kg] divided by its duration
        segment_duration[i] = t[i+1] - t[i] [s], giving kg/s for the whole
        aircraft, clipped at 0. fuel_flow[-1] is NaN (no next mass), so the
        total fuel burn equals mass[0] - mass[-1] (audit D3).

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

        # mass_diff[i] = mass[i+1] - mass[i] (forward, kg), over the same
        # segment as segment_duration[i] = t[i+1] - t[i] (s). The last value is
        # NaN: there is no next mass (audit D3).
        mass_diff = np.diff(mass_vals, append=np.nan)
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
        """Choose the mass strategy and run the performance model with it.

        Returns both perf output and q_fuel_used. In order of priority:

        1. ``aircraft_mass`` column (AO): used point by point.
        2. ``fuel_flow`` column (AO) without ``aircraft_mass``: the mass starts
           at the ``takeoff_weight`` attribute, or at the estimate from the AO
           trip fuel, and decreases with the AO fuel flow
           (``_performance_from_ao_fuel_flow``, audit A13).
        3. ``takeoff_weight`` attribute: the mass decreases with the BADA fuel
           flow (``_single_pass_performance``).
        4. Otherwise the iterative estimate with the BADA trip fuel
           (``_estimate_initial_mass_iterative``).

        BADA computes thrust and its own fuel flow at that mass in every case.
        """

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

        if _has_ao_fuel_flow_without_mass(df):
            self.logger.debug(
                "'fuel_flow' column provided without 'aircraft_mass': the mass"
                " decreases with the AO fuel flow"
            )
            perf = self._performance_from_ao_fuel_flow(
                adapter, df, flight, icao, q_fuel_used, reference_q_fuel
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

    def _performance_from_ao_fuel_flow(
        self,
        adapter: BaseBADAAdapter,
        df: pd.DataFrame,
        flight: Flight,
        icao: str,
        q_fuel_used: float,
        default_q_fuel: float,
    ) -> PerfOutput:
        """Mass from the AO fuel flow when the AO gives no ``aircraft_mass`` (audit A13).

        All masses in kg. The initial mass is the ``takeoff_weight`` attribute
        when given, otherwise min(MTOW, ZFW + trip fuel x
        (1 + fuel_reserve_fraction)) with ZFW from
        ``_zero_fuel_weight`` and trip fuel = sum of AO
        fuel_flow [kg/s] x segment_duration [s]. That trip fuel is known, so
        no iteration is needed. The mass then decreases with the AO fuel flow
        (``_mass_from_fuel_flow``), so mass[0] - mass[-1] equals the reported
        fuel (sum of ``fuel_burn``). A segment with an empty AO fuel flow
        (none is expected: empty values are interpolated at resampling) counts
        as 0 kg, as in the reported fuel. A final mass below OEW is logged as
        a warning and not clipped. BADA then computes thrust and its own fuel
        flow (used for the engine efficiency when it is missing) at each mass.
        The AO fuel flow is used as given: no q_fuel correction.
        """
        fuel_flow = pd.to_numeric(df["fuel_flow"], errors="coerce").to_numpy(
            dtype=float
        )
        segment_duration = df["segment_duration"].to_numpy(dtype=float)
        trip_fuel = float(_fuel_burn_per_segment(fuel_flow, segment_duration).sum())

        takeoff_weight: float | None = flight.attrs.get("takeoff_weight")
        if takeoff_weight is not None:
            self.logger.debug("'takeoff_weight' attribute provided, using it")
            initial_mass = float(takeoff_weight)
        else:
            zfw = _zero_fuel_weight(
                adapter, flight, icao, self.params.payload_factor, self.logger
            )
            fuel_factor = 1.0 + self.params.fuel_reserve_fraction
            initial_mass = min(
                zfw.maximum_takeoff_weight,
                zfw.zero_fuel_weight + trip_fuel * fuel_factor,
            )
            self.logger.debug(
                "Initial mass from the AO trip fuel (%s kg): %s kg. MTOW: %s kg",
                trip_fuel,
                initial_mass,
                zfw.maximum_takeoff_weight,
            )

        mass = _mass_from_fuel_flow(initial_mass, fuel_flow, segment_duration)

        oew = adapter.OEW
        if oew is not None and mass[-1] < oew:
            self.logger.warning(
                "Flight %s: the mass integrated from the AO fuel flow ends at"
                " %.0f kg, below OEW %.0f kg (initial mass %.0f kg, AO fuel"
                " %.0f kg); not clipped",
                flight.attrs.get("flight_id"),
                mass[-1],
                oew,
                initial_mass,
                trip_fuel,
            )

        return self._single_pass_performance(
            adapter,
            df.assign(aircraft_mass=mass),
            initial_mass=None,
            q_fuel_used=q_fuel_used,
            default_q_fuel=default_q_fuel,
        )

    def _single_pass_performance(
        self,
        adapter: BaseBADAAdapter,
        df: pd.DataFrame,
        initial_mass: float | None,
        q_fuel_used: float,
        default_q_fuel: float,
    ) -> PerfOutput:
        """Single pass performance calculation with given or initial mass.
        Now applies q_fuel correction during calculation.

        With ``initial_mass`` [kg, at the first retained trajectory point] the
        mass is integrated with the BADA fuel flow
        (mass -= ff_corrected [kg/s] x segment_duration [s]); callers pass it
        only when no AO ``fuel_flow`` column is given. Without it, the
        ``aircraft_mass`` column [kg] is used point by point (the AO column,
        or the mass integrated from the AO fuel flow). Returned fuel flow is kg/s for the
        whole aircraft and thrust is N.

        A point where BADA raises, or gives a fuel flow that is not finite,
        negative or above ``ff_outlier_threshold`` [kg/s], takes the values of
        the previous point; more than ``max_consecutive_failures`` such points
        in a row, or such a first point, fail the attempt (retryable).
        """

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

        # Calculate correction ratio (dimensionless: J/kg / J/kg).
        # ff_corrected [kg/s] = ff_BADA / (q_fuel_used / reference_q_fuel), so
        # ff_corrected x q_fuel_used = ff_BADA x reference_q_fuel (see
        # ``reference_q_fuel`` in BADAPerformanceModelParams).
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
                    _as_float(pt.acceleration),  # m/s^2
                    _as_float(pt.delta_tau),  # K
                )

                # Apply q_fuel correction immediately
                ff_corrected = _as_float(ff) / q_fuel_ratio
                thrust_val = _as_float(thrust)
                phase_val = phase
                segment_val = str(thrust_seg)

                # A non-finite fuel flow (e.g. BADA at a NaN TAS) is handled like
                # an outlier. NaN fails both comparisons, so without the
                # isfinite test it became the "previous" value and made the
                # integrated mass NaN for the rest of the flight (audit I13).
                if (
                    not np.isfinite(ff_corrected)
                    or (ff_corrected > ff_outlier_threshold)
                    or (ff_corrected < 0.0)
                ):
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
        """Iterative initial mass estimation using BADA performance model.

        All masses in kg. Initial mass = min(MTOW, ZFW + trip fuel x
        (1 + fuel_reserve_fraction)), with ZFW = OEW + payload_factor x MPL
        (or x (MTOW - OEW) when MPL is missing or not positive) and trip fuel = sum of BADA fuel
        flow [kg/s] x segment_duration [s] (NaN skipped). Used only when the AO
        gives no ``aircraft_mass``, no ``fuel_flow`` and no ``takeoff_weight``;
        with an AO fuel flow the trip fuel is known and
        ``_performance_from_ao_fuel_flow`` is used instead.
        """

        zfw = _zero_fuel_weight(
            adapter, flight, icao, self.params.payload_factor, self.logger
        )
        operating_empty_weight = zfw.operating_empty_weight
        maximum_takeoff_weight = zfw.maximum_takeoff_weight
        payload_factor = zfw.payload_factor
        zero_fuel_weight = zfw.zero_fuel_weight
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
        Now uses the correct q_fuel_used value.

        Overall propulsion efficiency (dimensionless) from pycontrails
        ``overall_propulsion_efficiency``: thrust [N] x TAS [m/s] /
        (BADA fuel flow [kg/s] x q_fuel_used [J/kg]), clipped to [0, 0.5].
        By design it uses the BADA fuel flow, not a provided ``fuel_flow``.
        Runs only when the column is absent: NaN values in a provided column
        are not filled, and provided values are not clipped.
        """

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
        """Write BADA outputs to ``df``.

        ``thrust`` [N]; ``aircraft_mass`` [kg] is the input column when given,
        otherwise the mass integrated with the AO fuel flow when it is given,
        otherwise with the BADA fuel flow (the constant first-pass guess if
        ``max_mass_estimation_iter`` <= 1); a provided or
        mass-derived ``fuel_flow`` [kg/s] is kept as is; ``fuel_burn`` =
        fuel_flow x segment_duration [kg per segment].
        """
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
        # n_engine: engine count. pycontrails Emissions divides fuel_flow by
        # n_engine to get per-engine flow, so fuel_flow is treated as
        # whole-aircraft flow.
        out.attrs["n_engine"] = nb_eng
        out.attrs["wingspan"] = adapter.span
        out.attrs["bada_version"] = bada_version
        out.attrs["bada_code"] = adapter.bada_code
        out.attrs["engine_uid"] = engine_id
