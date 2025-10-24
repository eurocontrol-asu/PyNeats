from __future__ import annotations
from typing import Protocol, Tuple, cast

from packaging import version
from pathlib import Path

from pycontrails.physics.units import m_per_s_to_knots, ft_to_m

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
]


class AircraftProtocol(Protocol):
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
    def thrust_fuel_segment(
        self,
        mass: float,
        alt_ft: float,
        tas_kt: float,
        vs_fpm: float,
        dtas_ktpm: float,
        delta_tau: float,
    ) -> Tuple[float, float, str, str]: ...


class BADA4Adapter(BaseBADAAdapter):
    def __init__(
        self,
        config_path: str,
        bada4_code: str,
        rocd_phase_threshold: float = 0.0,
    ) -> None:
        self.rocd_phase_threshold = rocd_phase_threshold

        bada_version = Path(config_path).name  # e.g. "4.2.1"
        v = version.parse(bada_version)
        short_version = f"{v.major}.{v.minor}"  # e.g. "4.2"

        self._obj = Bada4Aircraft(
            short_version,
            bada4_code,
            filePath=config_path,
        )
        self._bada_code = bada4_code

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

    # --- Core math (unchanged logic) ---
    def thrust_fuel_segment(
        self,
        mass: float,
        alt_ft: float,  # NOTE: Actually its called with m from bada_model.py
        tas_kt: float,  # NOTE: Actually its called with m / s from bada_model.py
        vs_fpm: float,
        dtas_ktpm: float,  # NOTE: Actually its called with m / s2 from bada_model.py
        delta_tau: float,
    ) -> Tuple[float, float, str, str]:
        # theta, delta, sigma = atm.atmosphereProperties(h=alt_ft, DeltaTau=delta_tau)
        theta, delta, sigma = atm.atmosphereProperties(alt_ft, delta_tau)

        v = m_per_s_to_knots(tas_kt)

        m, cas, tas = atm.convertSpeed(
            v=v,  # Input must be in kt. OK
            speedType="TAS",
            theta=theta,
            delta=delta,
            sigma=sigma,
        )

        # tau_const = theta * const.tau_0 / (theta * const.tau_0 - delta_tau)
        tau_const = theta * const.temp_0 / (theta * const.temp_0 - delta_tau)

        rocd = ft_to_m(vs_fpm) / 60  # NOTE: now in m/s
        acc = dtas_ktpm

        phase = (
            "Climb"
            if vs_fpm > self.rocd_phase_threshold
            else "Descent"
            if vs_fpm < -self.rocd_phase_threshold
            else "Cruise"
        )

        cfg = self._obj.flightEnvelope.getConfig(
            phase=phase,
            h=alt_ft,  # Actually is in meters
            mass=mass,
            v=cas,  # Calibrated airspeed (CAS) [m/s]
            deltaTemp=delta_tau,
            hRWY=0.0,
        )

        hlid, lg = self._obj.flightEnvelope.getAeroConfig(config=cfg)

        cl = self._obj.CL(M=m, delta=delta, mass=mass)
        cd = self._obj.CD(M=m, CL=cl, HLid=hlid, LG=lg)
        drag = self._obj.D(M=m, delta=delta, CD=cd)

        rocd_term = rocd * mass * const.g * tau_const / tas  # in meters per second
        thrust = rocd_term + mass * acc + drag

        thrust_idle = self._obj.Thrust(
            rating="LIDL",
            delta=delta,
            theta=theta,
            M=m,
            deltaTemp=delta_tau,
        )

        thrust_mcmb = self._obj.Thrust(
            rating="MCMB",
            delta=delta,
            theta=theta,
            M=m,
            deltaTemp=delta_tau,
        )

        # NOTE: We just replicated the logic of BADA. But I would:
        # 1) Here clip the thrust:
        # thrust = min(max(thrust, thrust_idle), thrust_mcmb)
        # 2) Then compute the fuel flow for that clipped thrust
        # 3) Finally, clip the fuel flow if needed (but only for idle IMHO)
        # ff = min(max(ff, ff_idle), ff_mcmb)

        ct = self._obj.CT(
            Thrust=thrust,
            delta=delta,
        )

        ff = self._obj.ff(
            CT=ct,
            delta=delta,
            theta=theta,
            M=m,
            deltaTemp=delta_tau,
        )

        ff_idle = self._obj.ff(
            rating="LIDL",
            delta=delta,
            theta=theta,
            M=m,
            deltaTemp=delta_tau,
        )

        ff_mcmb = self._obj.ff(
            rating="MCMB",
            delta=delta,
            theta=theta,
            M=m,
            deltaTemp=delta_tau,
        )

        # in BADA4Adapter.thrust_fuel_segment, after computing the six scalars:
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


class BADA3Adapter(BaseBADAAdapter):
    def __init__(
        self,
        config_path: str,
        bada3_code: str,
        rocd_phase_threshold: float = 0.0,
    ) -> None:
        self.rocd_phase_threshold = rocd_phase_threshold
        bada_version = Path(config_path).name  # e.g. "3.13"

        self._obj = Bada3Aircraft(
            bada_version,
            bada3_code,
            filePath=config_path,
        )
        self._bada_code = bada3_code

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

    def thrust_fuel_segment(
        self,
        mass: float,
        alt_ft: float,
        tas_kt: float,
        vs_fpm: float,
        dtas_ktpm: float,
        delta_tau: float,
    ) -> Tuple[float, float, str, str]:
        theta, delta, sigma = atm.atmosphereProperties(alt_ft, delta_tau)

        v = m_per_s_to_knots(tas_kt)
        _, CAS, TAS = atm.convertSpeed(
            v=v,
            speedType="TAS",
            theta=theta,
            delta=delta,
            sigma=sigma,
        )
        # tau_const = theta * const.tau_0 / (theta * const.tau_0 - delta_tau)
        tau_const = theta * const.temp_0 / (theta * const.temp_0 - delta_tau)

        rocd = ft_to_m(vs_fpm) / 60
        acc = dtas_ktpm

        phase = (
            "Climb"
            if vs_fpm > self.rocd_phase_threshold
            else "Descent"
            if vs_fpm < -self.rocd_phase_threshold
            else "Cruise"
        )

        cfg = self._obj.flightEnvelope.getConfig(
            phase=phase,
            h=alt_ft,  # Actually is in meters
            mass=mass,
            v=CAS,  # Calibrated airspeed (CAS) [m/s]
            deltaTemp=delta_tau,
            hRWY=0.0,
        )

        cl = self._obj.CL(tas=TAS, sigma=sigma, mass=mass)
        cd = self._obj.CD(CL=cl, config=cfg)
        drag = self._obj.D(tas=TAS, sigma=sigma, CD=cd)

        # Config is forced?
        thrust_idle = self._obj.Thrust(
            rating="LIDL",
            v=TAS,
            h=alt_ft,
            config="CR",  # Was forced in previous BADA3Adapter instead of using cfg (AP or LD). Why?
            deltaTemp=delta_tau,
        )

        thrust_mcmb = self._obj.Thrust(
            rating="MCMB",
            v=TAS,
            h=alt_ft,
            config=cfg,  # Does not depend on cfg anyway
            deltaTemp=delta_tau,
        )
        thrust = rocd * mass * const.g * tau_const / TAS + mass * acc + drag

        # NOTE: We just replicated the logic of BADA. But I would:
        # 1) Here clip the thrust:
        # thrust = min(max(thrust, thrust_idle), thrust_mcmb)
        # 2) Then compute the fuel flow for that clipped thrust
        # 3) Finally, clip the fuel flow if needed (but only for idle IMHO)
        # ff = min(max(ff, ff_idle), ff_mcmb)

        if phase == "Cruise":
            ff = self._obj.ff(
                flightPhase="Cruise",
                config=cfg,  # Does not depend on cfg anyway
                v=TAS,
                h=alt_ft,
                T=thrust,  # What if thrust is > Max thrust ? or below idle ...
            )
        else:  # Nominal thrust
            ff = self._obj.ff(
                flightPhase="Climb",
                config=cfg,  # Does not depend on cfg anyway
                v=TAS,
                h=alt_ft,
                T=thrust,  # What if thrust is > Max thrust ? Or below idle ...
            )

        # Idle fuel flow
        ff_idle = self._obj.ffMin(h=alt_ft)

        # Fuel flow at maximum climb thrust
        ff_mcmb = self._obj.ff(
            flightPhase="Climb",
            config=cfg,  # Does not depend on cfg anyway
            v=TAS,
            h=alt_ft,
            T=thrust_mcmb,
        )

        # Minimal None-guard + cast (keeps math identical, satisfies type checker)
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
