"""A supplied q_fuel outside 35-50 MJ/kg is rejected (audit A10).

q_fuel must be in J/kg. A value in MJ/kg (e.g. 43.05) is 1e6 times too small and
made the BADA fuel flow 1e6 times too large: every flight using it failed with
"BADA fuel flow is unrealistic", which does not point to the fuel value.

Now:
- an airport fuel file with such a value stops the run when the runner or the
  parser is built, naming the airports;
- a flight with such a value fails at parsing, naming the source (AO value or
  airport file);
- ``NEATSFuel`` refuses it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pyneats.core.neats_default_parameters import DEFAULT_Q_FUEL
from pyneats.core.neats_default_parameters import Q_FUEL_MAX
from pyneats.core.neats_default_parameters import Q_FUEL_MIN
from pyneats.core.neats_fuel import NEATSFuel
from pyneats.core.neats_fuel import check_q_fuel
from pyneats.runners.fleet import FleetRunnerParams
from pyneats.steps.parsing.neats_parser import NeatsTrajectoryParser
from pyneats.steps.parsing.neats_parser import _load_airport_fuel_props
from pyneats.steps.parsing.protocol import TrajectoryParserStepError
from pyneats.steps.weather.weather_store import ZarrPaths


REQUIRED_ATTRS = {
    "flight_id": "FL001",
    "aircraft_type": "A320",
    "departure_airport": "EGLL",
    "arrival_airport": "LFPG",
    "model_type": "BADA4",
    "aobt": "2023-01-01 10:00:00",
}


def _flight_df(**fuel_attrs: float) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "latitude": [51.5, 51.6],
            "longitude": [-0.1, 0.0],
            "altitude": [100, 200],
            "time": ["2023-01-01 10:00:00", "2023-01-01 10:05:00"],
        }
    )
    df.attrs = {**REQUIRED_ATTRS, **fuel_attrs}
    return df


def _airport_csv(tmp_path: Path, rows: dict[str, str]) -> str:
    # Same layout as the production file: ';' separator, decimal comma.
    p = tmp_path / "airport_fuel.csv"
    lines = ["Airport;aromatics_content;h_c_ratio;naphthalene;sulphur_content;q_fuel"]
    lines += [f"{a};0,2;;0,01;0,0001;{q}" for a, q in rows.items()]
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)


@pytest.mark.parametrize(
    "q", [Q_FUEL_MIN, Q_FUEL_MAX, DEFAULT_Q_FUEL, 41.944e6, 43.13e6, 45.5e6]
)
def test_plausible_q_fuel_accepted(q: float) -> None:
    assert check_q_fuel(q, "test") == q
    assert NEATSFuel(q_fuel=q).q_fuel == q


@pytest.mark.parametrize("q", [43.05, 43_050.0, 34.9e6, 50.1e6, float("nan")])
def test_implausible_q_fuel_rejected(q: float) -> None:
    with pytest.raises(ValueError, match="must be in J/kg"):
        check_q_fuel(q, "test")
    with pytest.raises(ValueError, match="outside the plausible range"):
        NEATSFuel(q_fuel=q)


def test_default_q_fuel_unchanged() -> None:
    assert NEATSFuel().q_fuel == DEFAULT_Q_FUEL


def test_airport_file_in_mj_per_kg_rejected_at_load(tmp_path: Path) -> None:
    path = _airport_csv(tmp_path, {"EGLL": "43000000", "EKYT": "43,05"})
    with pytest.raises(ValueError, match=r"1 airport\(s\) \(EKYT=43.05\)"):
        _load_airport_fuel_props(path)


def test_airport_file_in_j_per_kg_loads(tmp_path: Path) -> None:
    path = _airport_csv(tmp_path, {"EGLL": "43000000", "EKYT": "43050000"})
    props = _load_airport_fuel_props(path)
    assert props["EKYT"]["q_fuel"] == 43_050_000.0


def test_parser_with_wrong_airport_file_fails_at_construction(tmp_path: Path) -> None:
    path = _airport_csv(tmp_path, {"EGLL": "43,0"})
    with pytest.raises(ValueError, match="EGLL"):
        NeatsTrajectoryParser(airport_fuel_path=path)


def test_fleet_runner_params_check_airport_file(tmp_path: Path) -> None:
    # FleetRunner builds the parser lazily in each worker, so the file is
    # checked when the configuration is validated (FleetRunner.__init__).
    params = FleetRunnerParams(
        zarr_paths=ZarrPaths(str(tmp_path / "met"), str(tmp_path / "rad")),
        trajectory_json_filepath=str(tmp_path / "flights.json"),
        airport_fuel_path=_airport_csv(tmp_path, {"EGLL": "43,0"}),
    )
    with pytest.raises(ValueError, match="EGLL"):
        params.validate()


def test_missing_airport_file_still_only_warns(tmp_path: Path) -> None:
    assert _load_airport_fuel_props(str(tmp_path / "missing.csv")) == {}


def test_flight_with_ao_q_fuel_in_mj_per_kg_fails_parsing() -> None:
    with pytest.raises(TrajectoryParserStepError, match="AO calorific_value"):
        NeatsTrajectoryParser().run(_flight_df(q_fuel=43.05))


def test_flight_with_airport_q_fuel_out_of_range_names_airport() -> None:
    # A file that bypassed the load check (e.g. a mapping set directly).
    parser = NeatsTrajectoryParser()
    parser._airport_fuel_props = {"EGLL": {"q_fuel": 43.05}}
    with pytest.raises(TrajectoryParserStepError, match="airport EGLL"):
        parser.run(_flight_df())


def test_flight_with_plausible_q_fuel_parses() -> None:
    flight = NeatsTrajectoryParser().run(_flight_df(q_fuel=43.05e6))
    assert flight.fuel.q_fuel == 43.05e6
