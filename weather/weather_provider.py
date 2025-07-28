from typing import Protocol, Tuple, Literal
from dataclasses import dataclass, field
import numpy as np


from pycontrails.core.met import MetDataset
from pycontrails import Flight
from pycontrails.models.humidity_scaling import ConstantHumidityScaling

@dataclass
class WeatherProviderParams:
    """
    Configuration parameters for ICON dataset buffering and interpolation.

    Attributes:
        lon_buf (Tuple[float, float]): Buffer to apply to longitude (degrees).
        lat_buf (Tuple[float, float]): Buffer to apply to latitude (degrees).
        time_buf (Tuple[np.timedelta64, np.timedelta64]): 
            Buffer to apply before/after time (hours).
        level_buf (Tuple[float, float]): Buffer to apply to pressure level (hPa).
        interpolation_method (Literal['linear', ...]): 
            Interpolation method for gridded data.
    """

    lon_buf: Tuple[float, float] = (0.0, 0.0)
    lat_buf: Tuple[float, float] = (0.0, 0.0)
    time_buf: Tuple[np.timedelta64, np.timedelta64] = (
        np.timedelta64(0, 'h'),
        np.timedelta64(0, 'h')
    )
    level_buf: Tuple[float, float] = (0.0, 0.0)
    interpolation_method: Literal['linear','nearest'] = 'linear'
    

        
class WeatherProviderProtocol(Protocol):
    """Protocol for weather data providers with met and radiation datasets."""

    def met(self) -> MetDataset:
        ...
        """get atmospheric variables"""

    def rad(self) -> MetDataset:
        ...
        """get radiance variables"""

    def intersect(self, flight: Flight) -> Flight:
        """Intersects weather data with a flight."""
        
    def downselect(self, flight: Flight) -> MetDataset:
        """Down sample weather data to match flight area."""
        
        
class WeatherProvider:
    """
    Base class for providing weather data
    
    Args:
        met: Meteorological dataset
        rad: Radiation dataset
        wind: Wind dataset to compute True air speed
        params: Provider-specific configuration
    """
    
    def __init__(
        self,
        met: MetDataset,
        rad: MetDataset,
        wind: MetDataset,
        params: WeatherProviderParams | None = None
    ) -> None:
        
        self.met = met
        self.rad = rad
        self.wind = wind
        self.params = params or WeatherProviderParams()

    def met(self) -> MetDataset:
        return self.met

    def rad(self) -> MetDataset:
        return self.rad
    
    def downselect(self, flight: Flight) -> MetDataset:
        """Down sample weather data to match flight area."""
        
        return  flight.downselect_met(
            self.met,
            longitude_buffer=self.params.lon_buf,
            latitude_buffer=self.params.lat_buf,
            time_buffer=self.params.time_buf,
            level_buffer=self.params.level_buf,
        )
    
    def intersect(self,
                  flight: Flight) -> Flight:
        
        """Intersects weather data with a flight and returns a Flight instance."""
        
        ds_met = self.downselect(flight)
        df = flight.dataframe.copy()
        
        for var in ["eastward_wind", "northward_wind", "air_temperature", "specific_humidity"]:
            df_alias = "u_wind" if var == "eastward_wind" else (
                       "v_wind" if var == "northward_wind" else var)
            val = flight.intersect_met(
                ds_met[var],
                method=self.params.interpolation_method
            )
            df[df_alias] = np.nan_to_num(val, nan=0.0) if "wind" in var or var == "specific_humidity" else val
        
        
        flight = Flight(df)
        scaler = ConstantHumidityScaling(rhi_adj=0.99)
        flight_scaled = scaler.eval(source=flight)

        return flight_scaled
        