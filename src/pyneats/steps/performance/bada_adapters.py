"""BADA Adapters Module

This module provides a unified interface to EUROCONTROL's Base of Aircraft Data (BADA)
models through adapter classes. It handles both BADA3 and BADA4 implementations with
consistent error handling and unit conversions.

Key Components:

1. Base Structures:
   - State: Encapsulates flight state (velocity, altitude, mass, etc.)
   - Atmosphere: Holds atmospheric properties (temperature, pressure ratios)
   - AircraftProtocol: Defines common aircraft metadata interface
   - BaseBADAAdapter: Abstract base for BADA implementations

2. Adapter Classes:
   - BADA3Adapter: Wrapper for BADA3 aircraft performance model
   - BADA4Adapter: Wrapper for BADA4 aircraft performance model
   Both provide:
   - Thrust and fuel flow calculations
   - Flight phase detection
   - Configuration management
   - Unit conversions

3. Implementation Notes:
   All calculations follow BADA specifications for:
   - Drag computation
   - Thrust levels (idle, climb, total)
   - Fuel flow rates
   - Configuration management
   - Atmospheric corrections
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Literal, Protocol, TypeVar, cast

from packaging import version
from pycontrails.physics.units import ft_to_m, m_per_s_to_knots

try:
    import pyBADA.atmosphere as atm
    import pyBADA.constants as const
    from pyBADA.bada3 import Bada3Aircraft
    from pyBADA.bada4 import Bada4Aircraft
except ImportError as e:
    raise RuntimeError(
        "PyBADA is not installed. Install it manually:\n"
        "    pip install pybada --ignore-requires-python --no-deps\n"
        "after installing pyneats."
    ) from e


from pyneats.steps.performance.protocol import PerformanceStepError

__all__ = [
    "AircraftProtocol",
    "BaseBADAAdapter",
    "BADA3Adapter",
    "BADA4Adapter",
    "FlightPhase",
]


FlightPhase = Literal["Climb", "Cruise", "Descent"]


# -----------------------------------------------------------------------------
# Protocols
# -----------------------------------------------------------------------------


@dataclass
class State:
    """Flight state needed by BADA performance methods."""

    v: float
    h: float
    m: float
    M: float
    config: str
    phase: FlightPhase


@dataclass
class Atmosphere:
    """Atmosphere properties needed by BADA performance methods."""

    delta_tau: float
    delta: float
    theta: float
    sigma: float


class AircraftProtocol(Protocol):
    """Common aircraft metadata accessors."""

    @property
    def nb_eng(self) -> int | None: ...

    @property
    def span(self) -> float | None: ...

    @property
    def MTOW(self) -> float | None: ...

    @property
    def bada_code(self) -> str: ...

    @property
    def MPL(self) -> float | None: ...

    @property
    def OEW(self) -> float | None: ...


class BaseBADAAdapter(AircraftProtocol, Protocol):
    """Common adapter interface.

    All inputs are **SI units**:
      - mass: kg
      - altitude_m: meters (geopotential meters as used in pyBADA atmosphere)
      - tas_mps: meters/second (TAS)
      - rocd_mps: meters/second (positive = climb)
      - accel_mps2: meters/second^2 (time derivative of TAS)
      - delta_tau: K (delta temperature vs ISA)
    """

    def thrust_fuel_segment(
        self,
        mass: float,
        altitude_m: float,
        tas_mps: float,
        rocd_mps: float,
        accel_mps2: float,
        delta_tau: float,
    ) -> tuple[float, float, FlightPhase, str]: ...


# -----------------------------------------------------------------------------
# Internal utilities (shared behavior)
# -----------------------------------------------------------------------------

TObj = TypeVar("TObj", Bada3Aircraft, Bada4Aircraft)


class _PyBADAAdapterBase(Generic[TObj]):
    """Mixin with shared behaviors and accessors for BADA3/4 adapters."""

    _obj: TObj

    def __init__(self, rocd_phase_threshold_fpm: float) -> None:
        # Keep API identical: the passed threshold is in fpm; store and reuse
        self._rocd_phase_threshold_mps = ft_to_m(rocd_phase_threshold_fpm) / 60.0

    # --- phase label determination (threshold in fpm, input in m/s) ---
    def _phase_from_rocd(self, rocd_mps: float) -> FlightPhase:
        if rocd_mps > self._rocd_phase_threshold_mps:
            return "Climb"
        if rocd_mps < -self._rocd_phase_threshold_mps:
            return "Descent"
        return "Cruise"

    def thrust_fuel_segment(
        self,
        mass: float,
        altitude_m: float,
        tas_mps: float,
        rocd_mps: float,
        accel_mps2: float,
        delta_tau: float,
    ) -> tuple[float, float, FlightPhase, str]:
        """Compute thrust and fuel flow for a flight segment."""

        # Get atmosphere properites
        theta, delta, sigma = atm.atmosphereProperties(altitude_m, delta_tau)

        # BADA API for convertSpeed expects knots; convert our TAS m/s
        v_kt = m_per_s_to_knots(tas_mps)

        M, CAS, TAS = atm.convertSpeed(
            v=v_kt,
            speedType="TAS",
            theta=theta,
            delta=delta,
            sigma=sigma,
        )

        # delta temperature constant used by BADA 4
        tau_const: float = theta * const.temp_0 / (theta * const.temp_0 - delta_tau)  # type: ignore

        # Get phase
        phase = self._phase_from_rocd(rocd_mps)

        # Get configuration
        cfg = self._obj.flightEnvelope.getConfig(
            phase=phase,
            h=altitude_m,  # pyBADA expects altitude [m]
            mass=mass,
            v=CAS,  # pyBADA expects calibrated airspeed (CAS), and not TAS [m/s]
            deltaTemp=delta_tau,
            hRWY=0.0,
        )

        # Define TEM state and atmosphere
        state = State(
            v=TAS,  # type: ignore
            h=altitude_m,
            m=mass,
            M=M,  # type: ignore
            config=cfg,
            phase=phase,
        )

        atmosphere = Atmosphere(
            delta_tau=delta_tau,
            delta=delta,  # type: ignore
            theta=theta,  # type: ignore
            sigma=sigma,  # type: ignore
        )

        # Compute drag from state and atmosphere
        drag = self.drag(state, atmosphere)  # type: ignore

        # Compute thrust
        thrust = self.required_thrust(
            rocd_mps=rocd_mps,
            mass=mass,
            tau_const=tau_const,
            TAS=TAS,  # type: ignore
            accel_mps2=accel_mps2,
            drag=drag,
        )

        thrust_idle = self.thrust_idle(state, atmosphere)
        thrust_mcmb = self.thrust_climb(state, atmosphere)
        ff_idle = self.fuel_flow_idle(state, atmosphere)
        ff_mcmb = self.fuel_flow_climb(state, atmosphere)
        ff = self.fuel_flow(state, atmosphere, thrust)

        return self._post_process(
            ff,
            thrust,
            ff_idle,
            thrust_idle,
            ff_mcmb,
            thrust_mcmb,
            phase,
        )

    def required_thrust(
        self,
        rocd_mps: float,
        mass: float,
        tau_const: float,
        TAS: float,
        accel_mps2: float,
        drag: float,
    ) -> float:
        """Compute required thrust from flight parameters."""

        return rocd_mps * mass * const.g * tau_const / TAS + mass * accel_mps2 + drag  # type: ignore

    @abstractmethod
    def drag(self, state: State, atmosphere: Atmosphere) -> float: ...

    @abstractmethod
    def thrust_idle(self, state: State, atmosphere: Atmosphere) -> float | None: ...

    @abstractmethod
    def thrust_climb(self, state: State, atmosphere: Atmosphere) -> float | None: ...

    @abstractmethod
    def fuel_flow_climb(self, state: State, atmosphere: Atmosphere) -> float | None: ...

    @abstractmethod
    def fuel_flow_idle(self, state: State, atmosphere: Atmosphere) -> float | None: ...

    @abstractmethod
    def fuel_flow(
        self, state: State, atmosphere: Atmosphere, thrust: float
    ) -> float | None: ...

    @staticmethod
    def _post_process(
        ff: float | None,
        thrust: float | None,
        ff_idle: float | None,
        thrust_idle: float | None,
        ff_mcmb: float | None,
        thrust_mcmb: float | None,
        phase: FlightPhase,
    ) -> tuple[float, float, FlightPhase, str]:
        if (
            ff is None
            or thrust is None
            or ff_idle is None
            or thrust_idle is None
            or ff_mcmb is None
            or thrust_mcmb is None
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


# -----------------------------------------------------------------------------
# BADA 4 Adapter
# -----------------------------------------------------------------------------


class BADA4Adapter(_PyBADAAdapterBase[Bada4Aircraft], BaseBADAAdapter):
    """BADA 4 Adapter implementation."""

    def __init__(
        self,
        config_path: str,
        bada4_code: str,
        rocd_phase_threshold_fpm: float = 0.0,
    ) -> None:
        super().__init__(rocd_phase_threshold_fpm)

        bada_version = Path(config_path).name  # e.g. "4.2.1"
        v = version.parse(bada_version)
        short_version = f"{v.major}.{v.minor}"  # e.g. "4.2"

        self._obj: Bada4Aircraft = Bada4Aircraft(
            short_version,
            bada4_code,
            filePath=config_path,
        )

        self._bada_code = bada4_code

    # ---- metadata passthroughs ----
    @property
    def nb_eng(self) -> int | None:
        value = getattr(self._obj, "n_eng", None)
        return cast(int | None, value)

    @property
    def span(self) -> float | None:
        value = getattr(self._obj, "span", None)
        return cast(float | None, value)

    @property
    def MTOW(self) -> float | None:
        value = getattr(self._obj, "MTOW", None)
        return cast(float | None, value)

    @property
    def MPL(self) -> float | None:
        value = getattr(self._obj, "MPL", None)
        return cast(float | None, value)

    @property
    def OEW(self) -> float | None:
        value = getattr(self._obj, "OEW", None)
        return cast(float | None, value)

    @property
    def bada_code(self) -> str:
        return self._bada_code

    def drag(self, state: State, atmosphere: Atmosphere) -> float:
        cfg = state.config
        delta = atmosphere.delta
        M = state.M
        mass = state.m

        hlid, lg = self._obj.flightEnvelope.getAeroConfig(config=cfg)
        cl = self._obj.CL(M=M, delta=delta, mass=mass)
        cd = self._obj.CD(M=M, CL=cl, HLid=hlid, LG=lg)
        return self._obj.D(M=M, delta=delta, CD=cd)

    def thrust_idle(self, state: State, atmosphere: Atmosphere) -> float | None:
        theta = atmosphere.theta
        delta = atmosphere.delta
        delta_tau = atmosphere.delta_tau
        M = state.M

        return self._obj.Thrust(
            rating="LIDL",
            delta=delta,
            theta=theta,
            M=M,
            deltaTemp=delta_tau,
        )

    def thrust_climb(self, state: State, atmosphere: Atmosphere) -> float | None:
        theta = atmosphere.theta
        delta = atmosphere.delta
        delta_tau = atmosphere.delta_tau
        M = state.M

        return self._obj.Thrust(
            rating="MCMB",
            delta=delta,
            theta=theta,
            M=M,
            deltaTemp=delta_tau,
        )

    def fuel_flow_climb(self, state: State, atmosphere: Atmosphere) -> float | None:
        theta = atmosphere.theta
        delta = atmosphere.delta
        delta_tau = atmosphere.delta_tau
        M = state.M

        return self._obj.ff(
            rating="MCMB",
            delta=delta,
            theta=theta,
            M=M,
            deltaTemp=delta_tau,
        )

    def fuel_flow_idle(self, state: State, atmosphere: Atmosphere) -> float | None:
        theta = atmosphere.theta
        delta = atmosphere.delta
        delta_tau = atmosphere.delta_tau
        M = state.M

        return self._obj.ff(
            rating="LIDL",
            delta=delta,
            theta=theta,
            M=M,
            deltaTemp=delta_tau,
        )

    def fuel_flow(
        self, state: State, atmosphere: Atmosphere, thrust: float
    ) -> float | None:
        delta = atmosphere.delta
        M = state.M
        delta_tau = atmosphere.delta_tau
        theta = atmosphere.theta

        ct = self._obj.CT(
            Thrust=thrust,
            delta=delta,
        )

        return self._obj.ff(
            CT=ct,
            delta=delta,
            theta=theta,
            M=M,
            deltaTemp=delta_tau,
        )


# -----------------------------------------------------------------------------
# BADA 3 Adapter
# -----------------------------------------------------------------------------


class BADA3Adapter(_PyBADAAdapterBase[Bada3Aircraft], BaseBADAAdapter):
    """BADA 3 Adapter implementation."""

    def __init__(
        self,
        config_path: str,
        bada3_code: str,
        rocd_phase_threshold_fpm: float = 0.0,
    ) -> None:
        super().__init__(rocd_phase_threshold_fpm)
        bada_version = Path(config_path).name  # e.g. "3.13"
        self._obj: Bada3Aircraft = Bada3Aircraft(
            bada_version,
            bada3_code,
            filePath=config_path,
        )
        self._bada_code = bada3_code

    # ---- metadata passthroughs ----
    @property
    def nb_eng(self) -> int | None:
        value = getattr(self._obj, "numberOfEngines", None)
        return cast(int | None, value)

    @property
    def span(self) -> float | None:
        value = getattr(self._obj, "span", None)
        return cast(float | None, value)

    @property
    def MTOW(self) -> float | None:
        value = getattr(self._obj, "MTOW", None)
        return cast(float | None, value)

    @property
    def MPL(self) -> float | None:
        return None  # BADA3 has no MPL attribute ...

    @property
    def OEW(self) -> float | None:
        value = getattr(self._obj, "OEW", None)
        return cast(float | None, value)

    @property
    def bada_code(self) -> str:
        return self._bada_code

    def drag(self, state: State, atmosphere: Atmosphere) -> float:
        v = state.v
        sigma = atmosphere.sigma
        mass = state.m
        cfg = state.config

        cl = self._obj.CL(tas=v, sigma=sigma, mass=mass)
        cd = self._obj.CD(CL=cl, config=cfg)
        return self._obj.D(tas=v, sigma=sigma, CD=cd)

    def thrust_idle(self, state: State, atmosphere: Atmosphere) -> float | None:
        v = state.v
        altitude_m = state.h
        delta_tau = atmosphere.delta_tau

        return self._obj.Thrust(
            rating="LIDL",
            v=v,
            h=altitude_m,
            config="CR",  # emulates prior behavior
            deltaTemp=delta_tau,
        )

    def thrust_climb(self, state: State, atmosphere: Atmosphere) -> float | None:
        v = state.v
        altitude_m = state.h
        delta_tau = atmosphere.delta_tau
        cfg = state.config

        return self._obj.Thrust(
            rating="MCMB",
            v=v,
            h=altitude_m,
            config=cfg,
            deltaTemp=delta_tau,
        )

    def fuel_flow_idle(self, state: State, atmosphere: Atmosphere) -> float | None:
        altitude_m = state.h
        return self._obj.ffMin(h=altitude_m)

    def fuel_flow_climb(self, state: State, atmosphere: Atmosphere) -> float | None:
        TAS = state.v
        cfg = state.config
        altitude_m = state.h

        return self._obj.ff(
            flightPhase="Climb",
            config=cfg,
            v=TAS,
            h=altitude_m,
            T=self.thrust_climb(state, atmosphere),
        )

    def fuel_flow(
        self, state: State, atmosphere: Atmosphere, thrust: float
    ) -> float | None:
        v = state.v
        altitude_m = state.h
        phase = state.phase
        cfg = state.config

        if phase == "Cruise":
            return self._obj.ff(
                flightPhase="Cruise",
                config=cfg,
                v=v,
                h=altitude_m,
                T=thrust,
            )
        else:
            return self._obj.ff(
                flightPhase="Climb",
                config=cfg,
                v=v,
                h=altitude_m,
                T=thrust,
            )
