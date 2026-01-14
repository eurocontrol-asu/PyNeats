"""Fleet validation schemas (Layer 2).

This module provides declarative schemas for Fleet validation.
Schemas use primitive validators (Layer 1) to validate Fleet data.
Steps (Layer 3) declare INPUT_SCHEMA and OUTPUT_SCHEMA to validate their inputs/outputs.
"""

from dataclasses import dataclass

from pycontrails import Fleet

from pyneats.core.validators import validate_columns


@dataclass(frozen=True)
class FleetSchema:
    """Declarative schema for Fleet validation.

    Attributes:
        required_columns: Column names that must be present in Fleet.data
        optional_columns: Column names that may be present (for documentation)
    """

    required_columns: frozenset[str]
    optional_columns: frozenset[str] = frozenset()

    def validate(self, fleet: Fleet) -> None:
        """Validate fleet against schema.

        Args:
            fleet: Fleet to validate

        Raises:
            ValidationError: If validation fails
        """
        validate_columns(fleet.data, self.required_columns, self.optional_columns)


# Predefined schemas for common step inputs/outputs

SCHEMA_FLIGHT_4D = FleetSchema(
    required_columns=frozenset(
        {
            "latitude",
            "longitude",
            "altitude",
            "time",
        }
    ),
)

SCHEMA_WEATHER = FleetSchema(
    required_columns=frozenset(
        {
            "air_temperature",
            "specific_humidity",
            "eastward_wind",
            "northward_wind",
            "air_pressure",
        }
    ),
    optional_columns=frozenset(
        {
            "geopotential",
            "potential_vorticity",
            "rhi",
        }
    ),
)

SCHEMA_PERFORMANCE = FleetSchema(
    required_columns=frozenset(
        {
            "fuel_flow",
            "rocd",
            "rocd_min",
            "rocd_max",
            "tas",
        }
    ),
    optional_columns=frozenset(
        {
            "thrust",
            "engine_efficiency",
            "aircraft_mass",
        }
    ),
)

SCHEMA_EMISSIONS = FleetSchema(
    required_columns=frozenset(
        {
            "nvpm_ei_n",
            "nvpm_ei_m",
            "co2",
            "nox_ei",
        }
    ),
    optional_columns=frozenset(
        {
            "h2o",
            "so2",
            "co_ei",
            "hc_ei",
        }
    ),
)

SCHEMA_CONTRAILS = FleetSchema(
    required_columns=frozenset(
        {
            "ef",
            "contrail_age",
            "width",
            "depth",
            "n_ice_per_m_1",
        }
    ),
    optional_columns=frozenset(
        {
            "sdr_mean",
            "rsr_mean",
            "olr_mean",
            "rf_sw_mean",
            "rf_lw_mean",
            "rf_net_mean",
            "persistent_1",
        }
    ),
)
