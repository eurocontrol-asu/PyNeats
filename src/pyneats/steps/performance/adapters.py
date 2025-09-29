from __future__ import annotations
from typing import Protocol, Tuple

import pyBADA.constants as const
import pyBADA.conversions as conv
import pyBADA.atmosphere as atm
from pyBADA.bada3 import Bada3Aircraft
from pyBADA.bada4 import Bada4Aircraft

__all__ = ["AircraftProtocol", "BaseBADAAdapter", "BADA3Adapter", "BADA4Adapter"]

class PerformanceStepError(RuntimeError):
    """Raised when the performance step fails to evaluate or validate outputs."""

class AircraftProtocol(Protocol):
    @property
    def nb_eng(self) -> int: ...
    @property
    def span(self) -> float: ...
    @property
    def MTOW(self) -> float: ...
    @property
    def bada_code(self) -> str: ...

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
    def __init__(self, config_path: str, bada4_code: str) -> None:
        self._obj = Bada4Aircraft(config_path, bada4_code)
        self._bada_code = bada4_code

    @property
    def nb_eng(self) -> int: return self._obj.n_eng
    @property
    def span(self) -> float: return self._obj.span
    @property
    def MTOW(self) -> float: return self._obj.MTOW
    @property
    def bada_code(self) -> str: return self._bada_code

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
        self._bada_code = bada3_code

    @property
    def nb_eng(self) -> int: return self._obj.engines
    @property
    def span(self) -> float: return self._obj.span
    @property
    def MTOW(self) -> float: return self._obj.MTOW
    @property
    def bada_code(self) -> str: return self._bada_code

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