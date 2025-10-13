import unittest
from datetime import datetime
from weather_factory import WeatherFactoryParams, ERA5Factory, DWDFactory, WeatherCacheConfig
from weather_provider import WeatherProvider
from weather_store import ZarrPaths

class TestWeatherExtraction(unittest.TestCase):

    def setUp(self):
        self.params = WeatherFactoryParams(
            data_dir="/path/to/weather/data",
            cache=None,  # No cache for testing live extraction
            chunks={"time": 1, "latitude": 128, "longitude": 128},
        )
        self.asofdate = datetime(2023, 1, 1)

    def test_era5_extraction(self):
        factory = ERA5Factory(self.params)
        provider = factory(self.asofdate)

        self.assertIsInstance(provider, WeatherProvider)
        self.assertIsNotNone(provider.met())
        self.assertIsNotNone(provider.rad())
        self.assertIsNone(provider.wind())  # ERA5Factory does not provide wind by default

    def test_dwd_extraction(self):
        zarr_paths = ZarrPaths(
            met_store="/path/to/zarr/met.zarr",
            rad_store="/path/to/zarr/rad.zarr",
            wind_store="/path/to/zarr/wind.zarr",
        )
        self.params = WeatherFactoryParams(
            data_dir="/path/to/weather/data",
            cache=WeatherCacheConfig(zarr=zarr_paths),
        )
        factory = DWDFactory(self.params)
        provider = factory(self.asofdate)

        self.assertIsInstance(provider, WeatherProvider)
        self.assertIsNotNone(provider.met())
        self.assertIsNotNone(provider.rad())
        self.assertIsNotNone(provider.wind())

if __name__ == "__main__":
    unittest.main()