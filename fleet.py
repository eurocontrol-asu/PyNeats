from dataclasses import dataclass
from datetime import datetime, timedelta
import os
import pandas as pd
from joblib import Parallel, delayed
import time

from pyneats.flight import NeatsFlight
from pyneats.weather import DWDFactory, WeatherFactoryParams

NJOBS = 5

@dataclass(frozen=True)
class NeatsFleetParams:
    """
    Immutable container for fleet configuration.
    """
    model_type: str 
    weather_folder: str 
    trajectory_folder: str
    forecast_window: int

def process_flight_chunk(flight_list, weather):
    """
    Process a chunk (list) of flights with a single weather object
    and a single NeatsFlight object per chunk.
    Returns a list of results, one per flight.
    """
    results = []
      # Create ONCE per worker/chunk
    for df_flight in flight_list:
        try:
            neats_flight = NeatsFlight(weather=weather)
            neats_flight.source = df_flight    # Only update the flight source
            neats_flight.eval()
            results.append(neats_flight.climate_impact)
        except Exception as e:
            flight_id = df_flight['FLIGHT_ID'].iloc[0] if 'FLIGHT_ID' in df_flight else 'UNKNOWN'
            print(f"Error processing flight {flight_id}: {e}")
            results.append({})
    return results

def split_list(lst, n):
    """Split list `lst` into `n` nearly equal-sized chunks."""
    k, m = divmod(len(lst), n)
    return [lst[i*k + min(i, m):(i+1)*k + min(i+1, m)] for i in range(n)]

class NeatsFleet:
    """
    Processes a fleet of flights in parallel, with one weather object per process (chunked).
    """
    def __init__(self, 
                 asofdate: datetime, 
                 timeofday: int,
                 params: NeatsFleetParams,
                 sample: int = 0,
                 njobs: int = NJOBS):
        self.asofdate = asofdate
        self.timeofday = timeofday
        self.flights = None
        self.weather = None
        self.sample = sample
        self.njobs = njobs
        self.params = params 
        self.results = None
        
    def eval(self):
        self._get_weather()
        self._get_trajectories()
        #self._process_parallel()
        self.process_loop()
        
        
    def _process_loop(self):
        
        self.results = []
        
        for df_flight in self.flights:
            try:
                neats_flight = NeatsFlight(weather=self.weather)
                neats_flight.source = df_flight    # Only update the flight source
                neats_flight.eval()
                self.results.append(neats_flight.climate_impact)
            except Exception as e:
                flight_id = df_flight['FLIGHT_ID'].iloc[0] if 'FLIGHT_ID' in df_flight else 'UNKNOWN'
                print(f"Error processing flight {flight_id}: {e}")
                self.results.append({})
            
        
    def _process_parallel(self):
        """
        Split the list of flights into chunks, one per worker, 
        and process each chunk in parallel. Weather is only copied once per worker.
        """
        global_start = time.time()
        # Split flights list into njobs chunks
        chunks = split_list(self.flights, self.njobs)
        # Filter out empty chunks (may happen if njobs > num flights)
        chunks = [chunk for chunk in chunks if chunk]
        print(f"Processing {len(self.flights)} flights in {len(chunks)} parallel chunks...")

        all_results = Parallel(
            n_jobs=len(chunks),
            backend='loky'
        )(
            delayed(process_flight_chunk)(chunk, self.weather) for chunk in chunks
        )
        # Flatten the results list of lists
        self.results = [item for sublist in all_results for item in sublist]
        global_end = time.time()
        print(f"Global computational time: {global_end - global_start:.4f} seconds")
        
    def _get_weather(self):
        """
        Load weather data (heavy object) once, in the main process.
        This object will be copied once per chunk/worker.
        """
        self.weather = DWDFactory(WeatherFactoryParams(data_dir=self.params.weather_folder))(
            self.asofdate, self.timeofday
        )

    def _get_trajectories(self):
        self._get_raw_trajectories()
        self._filter_flights()
        
    def _get_trajectories_test(self):
        selected_trajectories = df_fleet.copy()
        self.flights = [group for _, group in selected_trajectories.groupby("FLIGHT_ID")]

    def _get_raw_trajectories(self):
        filename = f"Flights_{self.asofdate.strftime('%Y%m%d')}.csv"
        file_path = os.path.join(self.params.trajectory_folder, filename)
        try:
            self.raw_trajectories = pd.read_csv(
                file_path,
                sep=";",             
                decimal=",",         
                dayfirst=True        
            )
        except FileNotFoundError:
            print(f"Trajectory file not found: {file_path}")
            self.raw_trajectories = pd.DataFrame()

    def _filter_flights(self):
        window_start = self.asofdate + timedelta(hours=self.timeofday)
        window_end = window_start + timedelta(hours=self.params.forecast_window)
        df_model = self.raw_trajectories[self.raw_trajectories['MODEL_TYPE'] == self.params.model_type].copy()
        flight_id_cols = ['AIRCRAFT_ID', 'ADEP', 'ADES', 'REGISTRATION']
        df_model['FLIGHT_ID'] = df_model[flight_id_cols].astype(str).agg('_'.join, axis=1)
        timeover_parsed = pd.to_datetime(
            df_model['TIME_OVER'],
            format="%Y-%m-%d %H:%M:%S",
            errors='coerce'
        )
        df_model_sel = df_model.assign(TIMEOVER_PARSED=timeover_parsed)
        first_departure = (
            df_model_sel
            .sort_values(['FLIGHT_ID', 'TIMEOVER_PARSED'])
            .groupby('FLIGHT_ID', as_index=False)
            .first()[['FLIGHT_ID', 'TIMEOVER_PARSED']]
            .rename(columns={'TIMEOVER_PARSED': 'DEPARTURE_TIME'})
        )
        valid_flights = first_departure[
            (first_departure['DEPARTURE_TIME'] >= window_start) &
            (first_departure['DEPARTURE_TIME'] < window_end)
        ]['FLIGHT_ID']
        selected_trajectories = df_model[df_model['FLIGHT_ID'].isin(valid_flights)]
        if self.sample != 0:
            sample_flight_ids = valid_flights.head(self.sample)
            selected_trajectories = selected_trajectories[selected_trajectories['FLIGHT_ID'].isin(sample_flight_ids)]
        self.flights = [group for _, group in selected_trajectories.groupby("FLIGHT_ID")]