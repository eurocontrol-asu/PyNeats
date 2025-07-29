from typing import Protocol
from dataclasses import dataclass, field
from typing import Final, List, Optional
from datetime import datetime, timedelta
import xarray as xr
import re, os
from glob import glob

from pycontrails.datalib.ecmwf import ERA5
from pycontrails import DiskCacheStore, MetDataset
from pycontrails.models.cocip import Cocip
from pycontrails.core.met_var import MetVariable
from pycontrails.core.met_var  import (
    EastwardWind, NorthwardWind, VerticalVelocity, AirTemperature,
    SpecificHumidity, MassFractionOfCloudIceInAir, Geopotential,
    CloudAreaFractionInAtmosphereLayer, RelativeHumidity,
    TOANetDownwardShortwaveFlux, TOAOutgoingLongwaveFlux)

from pyneats.weather.weather_provider import WeatherProviderProtocol,WeatherProvider

DEFAULT_WEATHER_OFFSET: Final[int] = 36
DEFAULT_PRESSURE_LEVELS: Final[List[float]] = [550, 500, 450, 400, 350, 300, 250, 225, 200, 175, 150, 125]
DEFAULT_HORIZONTAL_RESOLUTION: Final[float] = 0.25
    
    


PotentialVorticity = MetVariable(
    short_name='pv',
    standard_name='potential_vorticity',
    long_name='Potential vorticity (K m^2 / kg s)',
    level_type='isobaricInhPa',
    ecmwf_id=60,
    grib1_id=128,
    grib2_id=(0,2,14),
    units='K m**2 kg**-1 s**-1',
    amip='pvu',
    description=(
        'Potential vorticity is a measure of the capacity for air to rotate in the '
        'atmosphere. If we ignore the effects of heating and friction, potential vorticity '
        'is conserved following an air parcel. It increases strongly above the tropopause '
        'and is used in studies related to stratosphere‑troposphere exchange and cyclogenesis.'
    )
)
    
@dataclass(frozen=True)
class WeatherFactoryParams:
    
    data_dir: str 
    horizontal_resolution: float = DEFAULT_HORIZONTAL_RESOLUTION
    pressure_levels: List[float] = field(default_factory=lambda: DEFAULT_PRESSURE_LEVELS.copy())
    weather_offset: int = DEFAULT_WEATHER_OFFSET
        
     

class WeatherFactoryProtocol(Protocol):
    def __call__(self, asofdate: datetime) -> WeatherProviderProtocol:
            ...

class ERA5Factory:
    
    def __init__(self, params: WeatherFactoryParams):
        self.params = params
        
    def __call__(self, asofdate: datetime) -> WeatherProviderProtocol:
        
        cache = DiskCacheStore(cache_dir=self.params.data_dir, allow_clear=True)
        
        time_bounds = self._make_time_bounds(asofdate)
        
        era5ml = ERA5(
            time=time_bounds,
            variables=Cocip.met_variables + Cocip.optional_met_variables,
            pressure_levels=self.params.pressure_levels,
            grid=self.params.horizontal_resolution,
            cachestore=cache
        )
        met = era5ml.open_metdataset()

        era5sl = ERA5(
            time=time_bounds,
            variables=Cocip.rad_variables,
            cachestore=cache,
            grid=self.params.horizontal_resolution,
        )
        rad = era5sl.open_metdataset()
        
        return WeatherProvider(met, rad, met)
    
    def _make_time_bounds(self, dt: datetime) -> tuple[str, str]:
        """
        Given a datetime, returns a tuple of ISO-formatted strings:
        (original, +1.5 days).

        Args:
            dt (datetime): input datetime.

        Returns:
            Tuple containing:
                - dt formatted as YYYY-MM-DD HH:MM:SS
                - dt + 36 hours formatted the same way
        """

        offset = timedelta(hours=self.params.weather_offset)
        dt_later = dt + offset

        fmt = "%Y-%m-%d %H:%M:%S"
        return (dt.strftime(fmt), dt_later.strftime(fmt))
    
class DWDFactory:
    """
    Factory to build WeatherProvider from DWD ICON-2mom forecast data.
    Separates MET, RADIATION, and WIND datasets in pycontrails-compatible format.
    """
    def __init__(self, params: WeatherFactoryParams):
        self.params = params

        # Maps for variable classification
        self.required_map = {
            'u': EastwardWind,
            'v': NorthwardWind,
            'omega': VerticalVelocity,
            'temp': AirTemperature,
            'qv': SpecificHumidity,
            'qi': MassFractionOfCloudIceInAir
        }
        
        self.optional_map = {'geopot': Geopotential,
            'clc': CloudAreaFractionInAtmosphereLayer,
            'rhi': RelativeHumidity,
            'pv' : PotentialVorticity
        }
        self.wind_map = {'u': EastwardWind, 'v': NorthwardWind}
        
        self.rad_map = {'tsr': TOANetDownwardShortwaveFlux,
                        'olr': TOAOutgoingLongwaveFlux}

    def __call__(self, asofdate: datetime, hour: Optional[int] = None) -> WeatherProviderProtocol:
        """
        Loads MET, RAD, WIND datasets for given datetime/run-hour,
        returns WeatherProvider(met, rad, wind)
        """
        run_hour = hour if hour is not None else asofdate.hour

        cache = DiskCacheStore(cache_dir=self.params.data_dir, allow_clear=True)

        date_str = asofdate.strftime("%Y%m%d")

        # Load and format MET dataset
        ds = self._load_and_standardize("MRV_T", date_str, run_hour, {**self.required_map, **self.optional_map, **self.rad_map})
        ds_met = ds[[v.standard_name for v in {**self.required_map, **self.optional_map}.values()]]
        met = MetDataset(ds_met)

        ds_rad = ds[[v.standard_name for v in self.rad_map.values()]]
        rad = MetDataset(ds_rad.expand_dims({'level': [-1]}))

        # Load and format WIND dataset (surface U/V), convert pressure to hPa
        ds_wind = self._load_and_standardize("MRV_T_UV", date_str, run_hour, self.wind_map)
        wind = MetDataset(ds_wind)

        return WeatherProvider(met, rad, wind)


    def _load_and_standardize(self, prefix: str, date_str: str, hour: int, var_map: dict) -> xr.Dataset:
        """
        Loads files for prefix/date/hour, renames dims and vars, converts pressure, returns dataset.
        """
        files = self._select_files(prefix, self.params.data_dir, date_str, hour)
        if not files:
            raise FileNotFoundError(f"No files for {prefix} on {date_str} at hour {hour:02d}")

        ds = xr.open_mfdataset(files, combine="by_coords")
        ds = self._standardize_dims(ds)

        # Convert plev (Pa) to level (hPa)
        ds['level'] = ds.level.astype('float64') / 100.0

        ds = self._standardize_vars(ds, var_map)
        ds.attrs.update({"provider": "DWD", "dataset": "ICON-2mom", "product": "forecast"})
        return ds

    def _load_radiation(self, ds_met: xr.Dataset) -> xr.Dataset:
        """
        Extracts and standardizes tsr/olr variables from MET dataset only.
        """
        present = [vn for vn in self.rad_map if vn in ds_met]
        if not present:
            raise ValueError("Radiation variables (tsr, olr) not found in MET dataset")

        ds = ds_met[present].copy()
        ds = self._standardize_vars(ds, self.rad_map)
        return ds

    @staticmethod
    def _select_files(prefix: str, directory: str, date: str, hour: int) -> List[str]:
        """
        Matches files like <prefix>_XXX_<YYYYMMDD><HH>.nc in given directory.
        """
        pattern = re.compile(fr"^{prefix}_\d{{3}}_{date}{hour:02d}\.nc$")
        return sorted(
            f for f in glob(os.path.join(directory, "*.nc"))
            if pattern.match(os.path.basename(f))
        )

    def _standardize_dims(self, ds: xr.Dataset) -> xr.Dataset:
        # Rename dimensions
        ds = ds.rename_dims({'plev': 'level', 'lat': 'latitude', 'lon': 'longitude'})
        # Also rename coordinate variables for consistency
        ds = ds.rename_vars({'plev': 'level', 'lat': 'latitude', 'lon': 'longitude'})
        if "U" in ds : 
            ds = ds.rename_vars({'U':'u', 'V':'v'})
        return ds

    @staticmethod
    def _standardize_vars(ds: xr.Dataset, var_map: dict) -> xr.Dataset:
        """
        Updates metadata and renames each raw var to its standard_name.
        """
        for raw, mv in var_map.items():
            if raw in ds:
                ds[raw].attrs.update({
                    "long_name": mv.long_name,
                    "standard_name": mv.standard_name,
                    "units": mv.units
                })
                ds = ds.rename({raw: mv.standard_name})
            else:
                print(f"NOTE: variable '{raw}' missing from dataset")
        return ds