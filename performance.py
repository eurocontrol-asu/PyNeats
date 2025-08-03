from typing import Protocol, Final, List, Tuple, Union, Dict, Any 
import pandas as pd
from dataclasses import dataclass, field
from enum import Enum
import pkg_resources
from importlib.resources import files
import numpy as np

from pycontrails import Flight
from pycontrails.physics.jet import acceleration, overall_propulsion_efficiency

import pyBADA.constants as const
import pyBADA.conversions as conv
import pyBADA.atmosphere as atm
from pyBADA.bada3 import Bada3Aircraft
from pyBADA.bada4 import Bada4Aircraft

from pyneats.utilities import is_nan_string


COLS_MAPPING_BADA: Final[List[str]] = ['NB_ENG','BADA3','BADA4','ENGINE_ID']
Q_FUEL: Final[float] = 43_130_000.0
DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW: Final[int] = 7
    
    
class FlightWithPerformance(Flight):
    
    @property
    def fuel(self) -> pd.Series:
        if "fuel" not in self:
            raise AttributeError("Flight has no 'fuel' column")
        return self["fuel"]
    
    @property
    def true_airspeed(self) -> pd.Series:
        if "true_airspeed" not in self:
            raise AttributeError("Flight has no 'true_airspeed' column")
        return self["true_airspeed"]
    
    @property
    def engine_efficiency(self) -> pd.Series:
        if "engine_efficiency" not in self:
            raise AttributeError("Flight has no 'engine_efficiency' column")
        return self["engine_efficiency"]
    

class FlightPerformanceModel(Protocol):
    def __call__(self, flight: Flight) -> FlightWithPerformance:
        ...
    
    
def load_bada_mapping():
    
    path = pkg_resources.resource_filename('pyneats.ressources', 'mapping_bada.csv')
    return pd.read_csv(path)


class AircraftProtocol(Protocol):
    """
    Protocol describing the interface expected from all aircraft classes.
    This allows your code to type-hint for any object that 'looks like' an aircraft,
    regardless of its underlying implementation.
    """
    @property
    def nb_eng(self) -> int:
        """Return the number of engines."""
        ...
        
    @property
    def span(self) -> float:
        """Return the number of engines."""
        ...
        
class BADA4Neats:
    """
    Adapter for Bada4Aircraft to expose a uniform interface.
    """
    def __init__(self, config_path: str, bada_4_code: str) -> None:
        self._obj = Bada4Aircraft(config_path, bada_4_code)
    
    @property
    def nb_eng(self) -> int:
        return self._obj.n_eng 
    
    @property
    def span(self) -> float:
        return self._obj.span

class BADA3Neats:
    """
    Adapter for Bada3Aircraft to expose a uniform interface.
    """
    def __init__(self, config_path: str, bada_3_code: str) -> None:
        self._obj = Bada3Aircraft(config_path, bada_3_code)
    
    @property
    def nb_eng(self) -> int:
        return self._obj.engines  #'engines' attribute in Bada3Aircraft
    
    @property
    def span(self) -> float:
        return self._obj.span
    
@dataclass(frozen=True)
class BADAPerformanceModelParams():
    
    true_air_speed_smoothing_window: int = DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW
    bada_mapping_file: pd.DataFrame = field(default_factory=load_bada_mapping)
    bada4_config_path = str(files('pyBADA').joinpath('4.2.1')) + '/'
    bada3_config_path = str(files('pyBADA').joinpath('3.16')) + '/'
    q_fuel: float = Q_FUEL
        
    def bada_type(self, icao: str) -> Tuple[int, str, str, str]:
        """Return NB_ENG, BADA3, BADA4, ENGINE_ID for the given ICAO."""
        
        df = self.bada_mapping_file
        row = df.loc[df.ICAO == icao, COLS_MAPPING_BADA]
        if row.empty:
            raise KeyError(f"No entry for ICAO '{icao}'")
        return tuple(row.iloc[0].tolist())
    
class BADAPerformanceModel():
    
    
    @staticmethod
    def _thrust_fuel_segment(
        aircraft: Union[Bada3Aircraft, Bada4Aircraft],
        mass: float,
        alt_ft: float,
        tas_kt: float,
        vs_fpm: float,
        dtas_ktpm: float,
        delta_tau: float
        ) -> Tuple[float, float, str, str]:
      
        theta, delta, sigma = atm.atmosphereProperties(h=alt_ft, DeltaTau=delta_tau)
        v = conv.ms2kt(tas_kt)
        M, CAS, TAS = atm.convertSpeed(v=v, speedType='TAS', theta=theta, delta=delta, sigma=sigma)
        tau_const = theta * const.tau_0 / (theta * const.tau_0 - delta_tau)
        rocd = conv.ft2m(vs_fpm) / 60
        acc = dtas_ktpm
        
        if isinstance(aircraft, Bada4Aircraft):
            
            phase = 'Climb' if vs_fpm > 20 else 'Descent' if vs_fpm < -20 else 'Cruise'

            cfg = aircraft.flightEnvelope.getConfig(
                h=alt_ft, phase=phase, theta=theta, delta=delta,
                v=CAS, mass=mass, DeltaTau=delta_tau, nz=1.2
            )

            HLid, LG = aircraft.flightEnvelope.getAeroConfig(config=cfg)

            CL = aircraft.CL(M=M, delta=delta, mass=mass)
            CD = aircraft.CD(M=M, CL=CL, HLid=HLid, LG=LG)
            Drag = aircraft.D(M=M, delta=delta, CD=CD)
            ROCD_term = rocd * mass * const.g * tau_const / TAS
            Thrust = ROCD_term + mass * acc + Drag

            Thrust_idle = aircraft.Thrust(rating='LIDL', delta=delta, theta=theta, M=M, DeltaTau=delta_tau)
            Thrust_MCMB = aircraft.Thrust(rating='MCMB', delta=delta, theta=theta, M=M, DeltaTau=delta_tau)

            CT = aircraft.CT(Thrust=Thrust, delta=delta)
            ff = aircraft.ff(CT=CT, delta=delta, theta=theta, M=M, DeltaTau=delta_tau)
            ff_idle = aircraft.ff(rating='LIDL', delta=delta, theta=theta, M=M, DeltaTau=delta_tau)
            ff_MCMB = aircraft.ff(rating='MCMB', delta=delta, theta=theta, M=M, DeltaTau=delta_tau)
            
        elif isinstance(aircraft, Bada3Aircraft):
            phase = 'cl' if vs_fpm > 0 else 'des' if vs_fpm < 0 else 'cr'

            cfg = aircraft.flightEnvelope.getConfig(
                h=alt_ft, phase=phase, v=CAS, mass=mass, DeltaTau=delta_tau)

            CL = aircraft.CL(tas=TAS, sigma=sigma, mass=mass)
            CD = aircraft.CD(CL=CL, config=cfg)
            Drag = aircraft.D(tas=TAS, sigma=sigma, CD=CD)

            Thrust_idle = aircraft.Thrust(rating='LIDL', v=TAS, h=alt_ft, config='CR', DeltaTau=delta_tau)
            Thrust_MCMB = aircraft.Thrust(rating='MCMB', v=TAS, h=alt_ft, DeltaTau=delta_tau)
            Thrust = rocd*mass*const.g*tau_const/TAS + mass*acc + Drag

            if phase == 'cr':
                ff = aircraft.ff(rating='MCRZ',v=TAS, h=alt_ft, T=Thrust)
            elif phase == 'cl':
                ff = aircraft.ff(rating='MCMB',v=TAS, h=alt_ft, T=Thrust)
            elif phase == 'des':
                ff = aircraft.ff(h=alt_ft, v=TAS, T=Thrust)

            ff_idle = aircraft.ff(rating='LIDL', h=alt_ft)
            ff_MCMB = aircraft.ff(rating='MCMB', v=TAS, h=alt_ft, T=Thrust_MCMB)

        if ff < ff_idle or Thrust < Thrust_idle:
            return ff_idle, Thrust_idle, phase, "LIDL"
        if ff > ff_MCMB or Thrust > Thrust_MCMB:
            return ff_MCMB, Thrust_MCMB, phase, "MCMB"
        return ff, Thrust, phase, "TOTAL"

    def _thrust_fuel_flight(self, aircraft, df: pd.DataFrame) -> Dict[str, List[float]]:
        """
        Calculates thrust and fuel flow along the flight using fast row iteration.
        """
        payload_factor = 0.867
        mass_curr = payload_factor * aircraft.MTOW

        # Pre-allocate result containers
        n = len(df)
        mass_arr = [0.0] * n
        ff_arr = [0.0] * n
        thrust_arr = [0.0] * n
        phase_arr = [""] * n
        segment_arr = [""] * n
        
        prev_ff = 0.0
        prev_thrust = 0.0
        prev_phase = ""
        prev_segment = ""


        for idx, pt in enumerate(df.itertuples(index=False, name="FlightPt")):
        #try:
            ff, thrust, phase, thrust_seg = self._thrust_fuel_segment(
                aircraft,
                mass_curr,
                pt.altitude,
                pt.true_airspeed,
                pt.rocd,
                pt.acceleration,
                pt.delta_tau
            )
            prev_ff, prev_thrust, prev_phase, prev_segment = ff, thrust, phase, thrust_seg

            '''    
            except Exception:
            # fallback: reuse previous values
                ff = prev_ff
                thrust = prev_thrust
                phase = prev_phase
                thrust_seg = prev_segment
            '''

            # record
            mass_arr[idx] = mass_curr
            ff_arr[idx] = ff
            thrust_arr[idx] = thrust
            phase_arr[idx] = phase
            segment_arr[idx] = thrust_seg

            # update mass
            mass_curr -= ff * pt.segment_duration

        return {
            "mass": mass_arr,
            "fuel_flow": ff_arr,
            "thrust": thrust_arr,
            "phase": phase_arr,
            "segment": segment_arr,
        }
    
    def _get_bada_aircraft(self, icao: str) -> AircraftProtocol:
        
        nb_eng, bada_3, bada_4, enfine_id = self.params.bada_type(icao)
        
        if is_nan_string(bada_4):
            return BADA3Neats(self.params.bada3_config_path, bada_3), "BADA3"
        else:
            return BADA4Neats(self.params.bada4_config_path, bada_4), "BADA4"
          
        
    
    def _compute_performance(self) -> FlightWithPerformance:
        
        icao = self.source.attrs["aircraft_type"]
        aircraft, bada_version = self._get_bada_aircraft(icao)
        
  
        df = self.flight_performance_df
        df["delta_tau"] = 0.0

        perf = self._thrust_fuel_flight(aircraft._obj, df)

        df["fuel_flow"] = perf["fuel_flow"]
        df["fuel_burn"] = df["fuel_flow"] * df["segment_duration"]
        df["thrust"] = perf["thrust"]
        df["aircraft_mass"] = perf["mass"]
        df["phase"] = perf["phase"]
        df["thrust_segment"] = perf["segment"]

        df["engine_efficiency"] = overall_propulsion_efficiency(
            df["true_airspeed"].values,
            df["thrust"].values,
            df["fuel_flow"].values,
            self.params.q_fuel,
            False,
            threshold=0.5,
        )
        
        flight_performance = Flight(self.flight_performance_df)
        flight_performance.attrs["n_engine"] = aircraft.nb_eng
        flight_performance.attrs["wingspan"] = aircraft.span
        flight_performance.attrs["bada_version"] = bada_version

        return flight_performance
    
    def _prepocessing(self) -> pd.DataFrame:
        
        flight_perfo_df = self.source.dataframe.copy()
        
        # Compute Ground speed using PyContrails method
        flight_perfo_df['ground_speed'] = self.source.segment_groundspeed()
        
        # Compute True air speed using PyContrails method
        flight_perfo_df['true_airspeed'] = self.source.segment_true_airspeed(
            u_wind=flight_perfo_df.u_wind,
            v_wind=flight_perfo_df.v_wind,
            smooth=True,
            window_length=self.params.true_air_speed_smoothing_window,
            polyorder=1
        )
        
        # Compute vertical speed and acceleration using PyContrails methods
        flight_perfo_df['segment_duration'] = self.source.segment_duration()
        flight_perfo_df['rocd'] = self.source.segment_rocd()
        flight_perfo_df['acceleration'] = acceleration(flight_perfo_df.true_airspeed, flight_perfo_df.segment_duration)
        
        return flight_perfo_df

        
    def __init__(self, params: BADAPerformanceModelParams| None = None):
        
        self.params = params or BADAPerformanceModelParams()
        
    def __call__(self, flight: Flight) -> FlightWithPerformance:
        
        self.source = flight
        
        self.flight_performance_df = self._prepocessing()
        
        return self._compute_performance()
        
       
    
    
class PerformanceModelType(Enum):
    """
    Enum that maps parser type descriptors to the actual class 
    """
    
    BADA = BADAPerformanceModel

    def get(self, params: Any | None = None) -> FlightPerformanceModel:
        return self.value(params=params)
