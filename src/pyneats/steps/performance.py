# performance.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from importlib.resources import files
from typing import Any, Final,  Protocol, Tuple, ClassVar, runtime_checkable
import pandas as pd
import numpy as np
from numpy.typing import NDArray

from pycontrails import Flight
from pycontrails.physics.jet import acceleration as pc_acceleration, overall_propulsion_efficiency

import pyBADA.constants as const
import pyBADA.conversions as conv
import pyBADA.atmosphere as atm
from pyBADA.bada3 import Bada3Aircraft
from pyBADA.bada4 import Bada4Aircraft

from pyneats.core.constants import Q_FUEL
from pyneats.utils.utilities import is_nan_string
from pyneats.core.views import FlightView
from pyneats.steps.weather.weather_provider import FlightWithWeather
from pyneats.core.steps import BaseStep, Step

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_REQUIRED_PERF_COLS",
    "FlightWithPerformance",
    "PerformanceStepError",
    "BADAPerformanceModelParams",
    "BADAPerformanceModel",
    "PerformanceModel",
    "PerformanceModelType",
]

# ---- configuration ----
COLS_MAPPING_BADA: tuple[str, ...] = ("NB_ENG", "BADA3", "BADA4", "ENGINE_ID")

DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW: Final[int] = 7
DEFAULT_REQUIRED_PERF_COLS: Final[tuple[str, ...]] = (
    "true_airspeed",
    "fuel_flow",
    "engine_efficiency",
)

# ---- error type ----
class PerformanceStepError(RuntimeError):
    """Raised when the performance step fails to evaluate or validate outputs."""

# ---- validated view (zero-copy) ----
class FlightWithPerformance(FlightView):
    """Zero-copy typed view for performance-enriched flights."""
    REQUIRED: ClassVar[tuple[str, ...]] = DEFAULT_REQUIRED_PERF_COLS

# ---- external mapping loader (kept separate for testability) ----
def load_bada_mapping() -> pd.DataFrame:
    import pkg_resources  # local import to keep import time light
    path = pkg_resources.resource_filename("pyneats.ressources", "mapping_bada.csv")
    return pd.read_csv(path)

# ---- aircraft interface & adapters ----
class AircraftProtocol(Protocol):
    @property
    def nb_eng(self) -> int: ...
    @property
    def span(self) -> float: ...
    @property
    def MTOW(self) -> float: ...  # needed for mass init

class BaseBADAAdapter(AircraftProtocol, Protocol):
    """Strategy interface for BADA thrust/fuel computations."""

    def thrust_fuel_segment(
        self,
        mass: float,
        alt_ft: float,
        tas_kt: float,
        vs_fpm: float,
        dtas_ktpm: float,
        delta_tau: float,
    ) -> Tuple[float, float, str, str]:
        """
        Return (fuel_flow, thrust, phase, thrust_segment_label).
        NOTE: math must remain identical to the legacy implementation.
        """
        ...

class BADA4Adapter(BaseBADAAdapter):
    def __init__(self, config_path: str, bada4_code: str) -> None:
        self._obj = Bada4Aircraft(config_path, bada4_code)

    # --- AircraftProtocol props ---
    @property
    def nb_eng(self) -> int: return self._obj.n_eng
    @property
    def span(self) -> float: return self._obj.span
    @property
    def MTOW(self) -> float: return self._obj.MTOW

    # --- Core math (unchanged logic) ---
    def thrust_fuel_segment(
        self,
        mass: float,
        alt_ft: float,
        tas_kt: float,
        vs_fpm: float,
        dtas_ktpm: float,
        delta_tau: float,
    ) -> Tuple[float, float, str, str]:
        theta, delta, sigma = atm.atmosphereProperties(h=alt_ft, DeltaTau=delta_tau)
        v = conv.ms2kt(tas_kt)
        m, cas, tas = atm.convertSpeed(v=v, speedType="TAS", theta=theta, delta=delta, sigma=sigma)
        tau_const = theta * const.tau_0 / (theta * const.tau_0 - delta_tau)
        rocd = conv.ft2m(vs_fpm) / 60
        acc = dtas_ktpm

        phase = "Climb" if vs_fpm > 20 else "Descent" if vs_fpm < -20 else "Cruise"

        cfg = self._obj.flightEnvelope.getConfig(
            h=alt_ft,
            phase=phase,
            theta=theta,
            delta=delta,
            v=cas,
            mass=mass,
            DeltaTau=delta_tau,
            nz=1.2,
        )

        hlid, lg = self._obj.flightEnvelope.getAeroConfig(config=cfg)

        cl = self._obj.CL(M=m, delta=delta, mass=mass)
        cd = self._obj.CD(M=m, CL=cl, HLid=hlid, LG=lg)
        drag = self._obj.D(M=m, delta=delta, CD=cd)
        rocd_term = rocd * mass * const.g * tau_const / tas
        thrust = rocd_term + mass * acc + drag

        thrust_idle = self._obj.Thrust(rating="LIDL", delta=delta, theta=theta, M=m, DeltaTau=delta_tau)
        thrust_mcmb = self._obj.Thrust(rating="MCMB", delta=delta, theta=theta, M=m, DeltaTau=delta_tau)

        ct = self._obj.CT(Thrust=thrust, delta=delta)
        ff = self._obj.ff(CT=ct, delta=delta, theta=theta, M=m, DeltaTau=delta_tau)
        ff_idle = self._obj.ff(rating="LIDL", delta=delta, theta=theta, M=m, DeltaTau=delta_tau)
        ff_mcmb = self._obj.ff(rating="MCMB", delta=delta, theta=theta, M=m, DeltaTau=delta_tau)

        # in BADA4Adapter.thrust_fuel_segment, after computing the six scalars:
        if (
            ff is None or thrust is None or
            ff_idle is None or thrust_idle is None or
            ff_mcmb is None or thrust_mcmb is None
        ):
            raise PerformanceStepError("BADA returned None in thrust/fuel computation")

        ff = float(ff)
        thrust = float(thrust)
        ff_idle = float(ff_idle)
        thrust_idle = float(thrust_idle)
        ff_mcmb = float(ff_mcmb)
        thrust_mcmb = float(thrust_mcmb)

        if ff < ff_idle or thrust < thrust_idle:
            return ff_idle, thrust_idle, phase, "LIDL"
        if ff > ff_mcmb or thrust > thrust_mcmb:
            return ff_mcmb, thrust_mcmb, phase, "MCMB"
        return ff, thrust, phase, "TOTAL"
        

class BADA3Adapter(BaseBADAAdapter):
    def __init__(self, config_path: str, bada3_code: str) -> None:
        self._obj = Bada3Aircraft(config_path, bada3_code)

    # --- AircraftProtocol props ---
    @property
    def nb_eng(self) -> int: return self._obj.engines
    @property
    def span(self) -> float: return self._obj.span
    @property
    def MTOW(self) -> float: return self._obj.MTOW

    # --- Core math (unchanged logic) ---
    # --- Core math (unchanged logic) ---
    def thrust_fuel_segment(
        self,
        mass: float,
        alt_ft: float,
        tas_kt: float,
        vs_fpm: float,
        dtas_ktpm: float,
        delta_tau: float,
    ) -> Tuple[float, float, str, str]:
        theta, delta, sigma = atm.atmosphereProperties(h=alt_ft, DeltaTau=delta_tau)
        v = conv.ms2kt(tas_kt)
        _, CAS, TAS = atm.convertSpeed(v=v, speedType="TAS", theta=theta, delta=delta, sigma=sigma)
        tau_const = theta * const.tau_0 / (theta * const.tau_0 - delta_tau)
        rocd = conv.ft2m(vs_fpm) / 60
        acc = dtas_ktpm

        phase = "cl" if vs_fpm > 0 else "des" if vs_fpm < 0 else "cr"

        cfg = self._obj.flightEnvelope.getConfig(
            h=alt_ft, phase=phase, v=CAS, mass=mass, DeltaTau=delta_tau
        )

        cl = self._obj.CL(tas=TAS, sigma=sigma, mass=mass)
        cd = self._obj.CD(CL=cl, config=cfg)
        drag = self._obj.D(tas=TAS, sigma=sigma, CD=cd)

        thrust_idle = self._obj.Thrust(rating="LIDL", v=TAS, h=alt_ft, config="CR", DeltaTau=delta_tau)
        thrust_mcmb = self._obj.Thrust(rating="MCMB", v=TAS, h=alt_ft, DeltaTau=delta_tau)
        thrust = rocd * mass * const.g * tau_const / TAS + mass * acc + drag

        if phase == "cr":
            ff = self._obj.ff(rating="MCRZ", v=TAS, h=alt_ft, T=thrust)
        elif phase == "cl":
            ff = self._obj.ff(rating="MCMB", v=TAS, h=alt_ft, T=thrust)
        else:  # "des"
            ff = self._obj.ff(h=alt_ft, v=TAS, T=thrust)

        ff_idle = self._obj.ff(rating="LIDL", h=alt_ft)
        ff_mcmb = self._obj.ff(rating="MCMB", v=TAS, h=alt_ft, T=thrust_mcmb)

        # Minimal None-guard + cast (keeps math identical, satisfies type checker)
        if (
            ff is None or thrust is None or
            ff_idle is None or thrust_idle is None or
            ff_mcmb is None or thrust_mcmb is None
        ):
            raise PerformanceStepError("BADA returned None in thrust/fuel computation")

        ff = float(ff)
        thrust = float(thrust)
        ff_idle = float(ff_idle)
        thrust_idle = float(thrust_idle)
        ff_mcmb = float(ff_mcmb)
        thrust_mcmb = float(thrust_mcmb)

        if ff < ff_idle or thrust < thrust_idle:
            return ff_idle, thrust_idle, phase, "LIDL"
        if ff > ff_mcmb or thrust > thrust_mcmb:
            return ff_mcmb, thrust_mcmb, phase, "MCMB"
        return ff, thrust, phase, "TOTAL"

# ---- params & model protocol ----
@dataclass(frozen=True)
class BADAPerformanceModelParams:
    true_air_speed_smoothing_window: int = DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW
    bada_mapping_file: pd.DataFrame = field(default_factory=load_bada_mapping)
    bada4_config_path: str = str(files("pyBADA").joinpath("4.2.1")) + "/"
    bada3_config_path: str = str(files("pyBADA").joinpath("3.16")) + "/"
    q_fuel: float = Q_FUEL

    def bada_type(self, icao: str) -> tuple[int, str, str, str]:
        df: pd.DataFrame = self.bada_mapping_file
        cols: list[str] = list(COLS_MAPPING_BADA)  # list, not tuple, helps type checkers
        mask = df["ICAO"] == icao

        if not mask.any():
            raise KeyError(f"No entry for ICAO '{icao}'")

        # row is a Series
        row = df.loc[mask, cols].iloc[0]

        nb_eng = int(row["NB_ENG"])
        bada3 = str(row["BADA3"])
        bada4 = str(row["BADA4"])
        engine_id = str(row["ENGINE_ID"])

        return nb_eng, bada3, bada4, engine_id
    
@runtime_checkable
class PerformanceModel(Step[FlightWithWeather, FlightWithPerformance], Protocol):
    """
    Performance steps consume a weather-enriched flight and produce
    a performance-enriched flight (zero-copy view).
    """
    # Protocol inherits: def __call__(self, flight: In) -> Out: ...

# ---- main model ----
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
        payload_factor = 0.867
        mass_curr: float = float(payload_factor * float(adapter.MTOW))

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



# ---- factory enum ----
class PerformanceModelType(Enum):
    BADA = BADAPerformanceModel

    def get(self, *args: Any, **kwargs: Any) -> PerformanceModel:
        impl = self.value  # type: ignore[assignment]
        return impl(*args, **kwargs)  # type: ignore[misc]
