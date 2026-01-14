"""Unit tests for Fleet validation schemas (Layer 2)."""

import pandas as pd
import pytest
from pycontrails import Fleet

from pyneats.core.schemas import (
    SCHEMA_CONTRAILS,
    SCHEMA_EMISSIONS,
    SCHEMA_FLIGHT_4D,
    SCHEMA_PERFORMANCE,
    SCHEMA_WEATHER,
    FleetSchema,
)
from pyneats.core.validators import ValidationError


class TestFleetSchema:
    """Test FleetSchema class."""

    def test_schema_is_frozen(self) -> None:
        """Test that FleetSchema is a frozen dataclass."""
        schema = FleetSchema(required_columns=frozenset({"a", "b"}))
        with pytest.raises(Exception):  # FrozenInstanceError
            schema.required_columns = frozenset({"c"})  # type: ignore[misc]

    def test_validate_with_all_required_columns(self) -> None:
        """Test that Fleet with all required columns passes validation."""
        df = pd.DataFrame({"latitude": [51.0, 52.0], "longitude": [0.0, 1.0], "time": pd.to_datetime([0, 60], unit="s"), "a": [1, 2], "b": [3, 4], "c": [5, 6]})
        fleet = Fleet(df)
        schema = FleetSchema(required_columns=frozenset({"a", "b"}))
        schema.validate(fleet)  # Should not raise

    def test_validate_with_optional_columns(self) -> None:
        """Test that optional columns are not enforced."""
        df = pd.DataFrame({"latitude": [51.0, 52.0], "longitude": [0.0, 1.0], "time": pd.to_datetime([0, 60], unit="s"), "a": [1, 2], "b": [3, 4]})
        fleet = Fleet(df)
        schema = FleetSchema(required_columns=frozenset({"a"}), optional_columns=frozenset({"c", "d"}))
        schema.validate(fleet)  # Should not raise (optional columns not present is OK)

    def test_validate_missing_required_column(self) -> None:
        """Test that missing required column raises ValidationError."""
        df = pd.DataFrame({"latitude": [51.0, 52.0], "longitude": [0.0, 1.0], "time": pd.to_datetime([0, 60], unit="s"), "a": [1, 2]})
        fleet = Fleet(df)
        schema = FleetSchema(required_columns=frozenset({"a", "b"}))
        with pytest.raises(ValidationError, match="Missing required columns: \\['b'\\]"):
            schema.validate(fleet)

    def test_validate_empty_required_columns(self) -> None:
        """Test that schema with no required columns passes validation."""
        df = pd.DataFrame({"latitude": [51.0, 52.0], "longitude": [0.0, 1.0], "time": pd.to_datetime([0, 60], unit="s"), "a": [1, 2]})
        fleet = Fleet(df)
        schema = FleetSchema(required_columns=frozenset())
        schema.validate(fleet)  # Should not raise

    def test_default_optional_columns_is_empty_frozenset(self) -> None:
        """Test that optional_columns defaults to empty frozenset."""
        schema = FleetSchema(required_columns=frozenset({"a"}))
        assert schema.optional_columns == frozenset()


class TestPredefinedSchemas:
    """Test predefined schemas for common step inputs/outputs."""

    def test_schema_flight_4d_valid(self) -> None:
        """Test SCHEMA_FLIGHT_4D with valid Fleet."""
        df = pd.DataFrame(
            {
                "latitude": [51.0, 52.0],
                "longitude": [0.0, 1.0],
                "altitude": [10000, 11000],
                "time": pd.to_datetime([100, 200], unit="s"),
            }
        )
        fleet = Fleet(df)
        SCHEMA_FLIGHT_4D.validate(fleet)  # Should not raise

    def test_schema_flight_4d_missing_column(self) -> None:
        """Test SCHEMA_FLIGHT_4D with missing required column."""
        df = pd.DataFrame({"latitude": [51.0], "longitude": [0.0], "time": pd.to_datetime([0], unit="s"), "altitude": [10000]})
        fleet = Fleet(df)
        # Remove time column after Fleet creation to test schema validation
        fleet.data = fleet.data.drop(columns=["time"])
        with pytest.raises(ValidationError, match="Missing required columns: \\['time'\\]"):
            SCHEMA_FLIGHT_4D.validate(fleet)

    def test_schema_weather_valid(self) -> None:
        """Test SCHEMA_WEATHER with valid Fleet."""
        df = pd.DataFrame(
            {
                "latitude": [51.0, 52.0],
                "longitude": [0.0, 1.0],
                "time": pd.to_datetime([0, 60], unit="s"),
                "air_temperature": [250.0, 260.0],
                "specific_humidity": [0.001, 0.002],
                "eastward_wind": [10.0, 15.0],
                "northward_wind": [5.0, 7.0],
                "air_pressure": [30000, 31000],
            }
        )
        fleet = Fleet(df)
        SCHEMA_WEATHER.validate(fleet)  # Should not raise

    def test_schema_weather_with_optional_columns(self) -> None:
        """Test SCHEMA_WEATHER with optional columns present."""
        df = pd.DataFrame(
            {
                "latitude": [51.0],
                "longitude": [0.0],
                "time": pd.to_datetime([0], unit="s"),
                "air_temperature": [250.0],
                "specific_humidity": [0.001],
                "eastward_wind": [10.0],
                "northward_wind": [5.0],
                "air_pressure": [30000],
                "geopotential": [100000],
                "potential_vorticity": [1e-5],
                "rhi": [0.8],
            }
        )
        fleet = Fleet(df)
        SCHEMA_WEATHER.validate(fleet)  # Should not raise

    def test_schema_weather_missing_required_column(self) -> None:
        """Test SCHEMA_WEATHER with missing required column."""
        df = pd.DataFrame(
            {
                "latitude": [51.0],
                "longitude": [0.0],
                "time": pd.to_datetime([0], unit="s"),
                "air_temperature": [250.0],
                "specific_humidity": [0.001],
                "eastward_wind": [10.0],
                "northward_wind": [5.0],
                # Missing air_pressure
            }
        )
        fleet = Fleet(df)
        with pytest.raises(ValidationError, match="Missing required columns: \\['air_pressure'\\]"):
            SCHEMA_WEATHER.validate(fleet)

    def test_schema_performance_valid(self) -> None:
        """Test SCHEMA_PERFORMANCE with valid Fleet."""
        df = pd.DataFrame(
            {
                "latitude": [51.0, 52.0],
                "longitude": [0.0, 1.0],
                "time": pd.to_datetime([0, 60], unit="s"),
                "fuel_flow": [1.0, 1.1],
                "rocd": [500, 600],
                "rocd_min": [400, 500],
                "rocd_max": [600, 700],
                "tas": [250, 260],
            }
        )
        fleet = Fleet(df)
        SCHEMA_PERFORMANCE.validate(fleet)  # Should not raise

    def test_schema_performance_with_optional_columns(self) -> None:
        """Test SCHEMA_PERFORMANCE with optional columns present."""
        df = pd.DataFrame(
            {
                "latitude": [51.0],
                "longitude": [0.0],
                "time": pd.to_datetime([0], unit="s"),
                "fuel_flow": [1.0],
                "rocd": [500],
                "rocd_min": [400],
                "rocd_max": [600],
                "tas": [250],
                "thrust": [50000],
                "engine_efficiency": [0.35],
                "aircraft_mass": [70000],
            }
        )
        fleet = Fleet(df)
        SCHEMA_PERFORMANCE.validate(fleet)  # Should not raise

    def test_schema_performance_missing_required_column(self) -> None:
        """Test SCHEMA_PERFORMANCE with missing required columns."""
        df = pd.DataFrame({"latitude": [51.0], "longitude": [0.0], "time": pd.to_datetime([0], unit="s"), "fuel_flow": [1.0], "rocd": [500]})
        fleet = Fleet(df)
        with pytest.raises(
            ValidationError, match="Missing required columns: \\['rocd_max', 'rocd_min', 'tas'\\]"
        ):
            SCHEMA_PERFORMANCE.validate(fleet)

    def test_schema_emissions_valid(self) -> None:
        """Test SCHEMA_EMISSIONS with valid Fleet."""
        df = pd.DataFrame(
            {
                "latitude": [51.0, 52.0],
                "longitude": [0.0, 1.0],
                "time": pd.to_datetime([0, 60], unit="s"),
                "nvpm_ei_n": [1e15, 1.1e15],
                "nvpm_ei_m": [0.01, 0.011],
                "co2": [3.16, 3.2],
                "nox_ei": [10.0, 11.0],
            }
        )
        fleet = Fleet(df)
        SCHEMA_EMISSIONS.validate(fleet)  # Should not raise

    def test_schema_emissions_with_optional_columns(self) -> None:
        """Test SCHEMA_EMISSIONS with optional columns present."""
        df = pd.DataFrame(
            {
                "latitude": [51.0],
                "longitude": [0.0],
                "time": pd.to_datetime([0], unit="s"),
                "nvpm_ei_n": [1e15],
                "nvpm_ei_m": [0.01],
                "co2": [3.16],
                "nox_ei": [10.0],
                "h2o": [1.24],
                "so2": [0.001],
                "co_ei": [0.5],
                "hc_ei": [0.1],
            }
        )
        fleet = Fleet(df)
        SCHEMA_EMISSIONS.validate(fleet)  # Should not raise

    def test_schema_emissions_missing_required_column(self) -> None:
        """Test SCHEMA_EMISSIONS with missing required column."""
        df = pd.DataFrame({"latitude": [51.0], "longitude": [0.0], "time": pd.to_datetime([0], unit="s"), "nvpm_ei_n": [1e15], "nvpm_ei_m": [0.01], "co2": [3.16]})
        fleet = Fleet(df)
        with pytest.raises(ValidationError, match="Missing required columns: \\['nox_ei'\\]"):
            SCHEMA_EMISSIONS.validate(fleet)

    def test_schema_contrails_valid(self) -> None:
        """Test SCHEMA_CONTRAILS with valid Fleet."""
        df = pd.DataFrame(
            {
                "latitude": [51.0, 52.0],
                "longitude": [0.0, 1.0],
                "time": pd.to_datetime([0, 60], unit="s"),
                "ef": [1.0, 1.1],
                "contrail_age": [0.0, 3600.0],
                "width": [100.0, 150.0],
                "depth": [200.0, 250.0],
                "n_ice_per_m_1": [1e11, 1.1e11],
            }
        )
        fleet = Fleet(df)
        SCHEMA_CONTRAILS.validate(fleet)  # Should not raise

    def test_schema_contrails_with_optional_columns(self) -> None:
        """Test SCHEMA_CONTRAILS with optional columns present."""
        df = pd.DataFrame(
            {
                "latitude": [51.0],
                "longitude": [0.0],
                "time": pd.to_datetime([0], unit="s"),
                "ef": [1.0],
                "contrail_age": [0.0],
                "width": [100.0],
                "depth": [200.0],
                "n_ice_per_m_1": [1e11],
                "sdr_mean": [100.0],
                "rsr_mean": [50.0],
                "olr_mean": [200.0],
                "rf_sw_mean": [10.0],
                "rf_lw_mean": [20.0],
                "rf_net_mean": [30.0],
                "persistent_1": [1],
            }
        )
        fleet = Fleet(df)
        SCHEMA_CONTRAILS.validate(fleet)  # Should not raise

    def test_schema_contrails_missing_required_column(self) -> None:
        """Test SCHEMA_CONTRAILS with missing required columns."""
        df = pd.DataFrame({"latitude": [51.0], "longitude": [0.0], "time": pd.to_datetime([0], unit="s"), "ef": [1.0], "contrail_age": [0.0]})
        fleet = Fleet(df)
        with pytest.raises(
            ValidationError, match="Missing required columns: \\['depth', 'n_ice_per_m_1', 'width'\\]"
        ):
            SCHEMA_CONTRAILS.validate(fleet)

    @pytest.mark.parametrize(
        "schema,required_count,optional_count",
        [
            (SCHEMA_FLIGHT_4D, 4, 0),
            (SCHEMA_WEATHER, 5, 3),
            (SCHEMA_PERFORMANCE, 5, 3),
            (SCHEMA_EMISSIONS, 4, 4),
            (SCHEMA_CONTRAILS, 5, 7),
        ],
    )
    def test_predefined_schema_column_counts(
        self, schema: FleetSchema, required_count: int, optional_count: int
    ) -> None:
        """Test that predefined schemas have expected column counts."""
        assert len(schema.required_columns) == required_count
        assert len(schema.optional_columns) == optional_count

    @pytest.mark.parametrize(
        "schema,expected_required_subset",
        [
            (SCHEMA_FLIGHT_4D, {"latitude", "longitude", "altitude", "time"}),
            (SCHEMA_WEATHER, {"air_temperature", "specific_humidity"}),
            (SCHEMA_PERFORMANCE, {"fuel_flow", "rocd", "tas"}),
            (SCHEMA_EMISSIONS, {"nvpm_ei_n", "co2", "nox_ei"}),
            (SCHEMA_CONTRAILS, {"ef", "contrail_age", "width"}),
        ],
    )
    def test_predefined_schema_required_columns(
        self, schema: FleetSchema, expected_required_subset: set[str]
    ) -> None:
        """Test that predefined schemas contain expected required columns."""
        assert expected_required_subset.issubset(schema.required_columns)
