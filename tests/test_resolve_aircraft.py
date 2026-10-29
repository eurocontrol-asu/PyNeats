"""``resolve_aircraft``: BADA model and engines of an aircraft, without a flight.

The performance step resolves its BADA adapter with the same function, so the
answer must be what a flight gets in ``attrs`` (``engine_uid``, ``n_engine``,
``aircraft_type``, ``bada_version``, ``bada_code``). The engine UID given to
pycontrails comes from the operator, from ``MRR_conservative_mapping.csv``,
or from the ECTL mapping row.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pyneats.core.neats_default_parameters import DEFAULT_BADA3_VERSION
from pyneats.core.neats_default_parameters import DEFAULT_BADA4_VERSION
from pyneats.steps.performance import EngineSource
from pyneats.steps.performance import ResolvedAircraft
from pyneats.steps.performance import resolve_aircraft
from pyneats.steps.performance.bada_model import BADAPerformanceModelParams


GOLDEN_DIR = Path(__file__).parent / "data" / "golden"


@pytest.fixture
def bada(bada_path: Path | None) -> Path:
    if bada_path is None or not (bada_path / DEFAULT_BADA4_VERSION).is_dir():
        pytest.skip("BADA data not available")
    return bada_path


@pytest.fixture
def fake_bada(tmp_path: Path) -> Path:
    """BADA root with empty BADA4 and BADA3 directories (mapping only)."""
    (tmp_path / DEFAULT_BADA4_VERSION).mkdir()
    (tmp_path / DEFAULT_BADA3_VERSION).mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# Engine source cases (real BADA data)
# ---------------------------------------------------------------------------


@pytest.mark.requires_bada
def test_mrr_conservative_engine(bada: Path) -> None:
    """A320 without a declared engine: BADA4 A320-214 (CFM56-5B4/P), but the
    emissions engine is the MRR conservative 1IA001 (V2527-A5)."""
    r = resolve_aircraft("A320", bada_path=bada)
    assert r == ResolvedAircraft(
        bada_version="BADA4",
        bada_release=DEFAULT_BADA4_VERSION,
        bada_model="A320-214",
        bada_engine="CFM56-5B4/P SAC",
        bada_engine_uid="3CM026",
        n_engine=2,
        aircraft_type="A320",
        emissions_engine_uid="1IA001",
        emissions_engine_source="MRR conservative",
    )


@pytest.mark.requires_bada
@pytest.mark.parametrize("engine_uid", ["3CM026", "CFM56-FAKE"])
def test_operator_engine(bada: Path, engine_uid: str) -> None:
    """A declared engine goes to pycontrails as given, known or not; the BADA
    model stays the one of the A320 mapping row."""
    r = resolve_aircraft("A320", engine_uid=engine_uid, bada_path=bada)
    assert r.emissions_engine_uid == engine_uid
    assert r.emissions_engine_source == "operator"
    assert r.bada_model == "A320-214"
    assert r.bada_engine_uid == "3CM026"
    assert r.n_engine == 2


@pytest.mark.requires_bada
def test_operator_engine_with_series(bada: Path) -> None:
    """(ICAO, SERIES, ENGINE_ID) row: the declared engine is the row engine."""
    r = resolve_aircraft("A30B", "A300B2 103", "3GE070", bada_path=bada)
    assert (r.bada_model, r.bada_engine_uid) == ("A300B4-203", "3GE070")
    assert (r.emissions_engine_uid, r.emissions_engine_source) == (
        "3GE070",
        "operator",
    )


@pytest.mark.requires_bada
def test_ectl_mapping_row_engine(bada: Path) -> None:
    """A342 is not in MRR_conservative_mapping.csv: the row engine is used."""
    r = resolve_aircraft("A342", bada_path=bada)
    assert r.bada_version == "BADA4"
    assert r.bada_model == "A340-213"
    assert r.bada_engine == "CFM56-5C4"
    assert r.n_engine == 4
    assert r.emissions_engine_uid == r.bada_engine_uid == "1CM010"
    assert r.emissions_engine_source == "ECTL mapping row"


@pytest.mark.requires_bada
@pytest.mark.parametrize(
    ("icao", "series", "model", "row_engine", "engine", "source"),
    [
        ("A320", "A320-212", "A320-212", "1CM009", "1IA001", "MRR conservative"),
        ("A342", "A340 212", "A340-213", "1CM011", "1CM011", "ECTL mapping row"),
    ],
)
def test_series_row_engine_source(
    bada: Path,
    icao: str,
    series: str,
    model: str,
    row_engine: str,
    engine: str,
    source: EngineSource,
) -> None:
    """(ICAO, SERIES) row without a declared engine: the series selects the
    row, and the emissions engine is the MRR one, else the row engine."""
    r = resolve_aircraft(icao, series, bada_path=bada)
    assert (r.bada_model, r.bada_engine_uid) == (model, row_engine)
    assert (r.emissions_engine_uid, r.emissions_engine_source) == (engine, source)


@pytest.mark.requires_bada
def test_bada3_only_type(bada: Path) -> None:
    """A124 has no BADA4 model: BADA3, no BADA engine name."""
    r = resolve_aircraft("A124", bada_path=bada)
    assert r.bada_version == "BADA3"
    assert r.bada_release == DEFAULT_BADA3_VERSION
    assert r.bada_model == "A124"
    assert r.bada_engine is None
    assert r.n_engine == 4
    assert r.emissions_engine_uid == "1ZM001"
    assert r.emissions_engine_source == "ECTL mapping row"


@pytest.mark.requires_bada
def test_force_bada3_keeps_engine(bada: Path) -> None:
    """The BADA3 retry changes the BADA model only."""
    r4 = resolve_aircraft("A320", bada_path=bada)
    r3 = resolve_aircraft("A320", bada_path=bada, force_bada3=True)
    assert (r3.bada_version, r3.bada_model, r3.bada_engine) == ("BADA3", "A320", None)
    assert r3.emissions_engine_uid == r4.emissions_engine_uid
    assert r3.n_engine == r4.n_engine


# ---------------------------------------------------------------------------
# Errors and wrapping (no BADA data needed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("icao", ["ZZZZ", ""])
def test_unknown_type_raises(fake_bada: Path, icao: str) -> None:
    with pytest.raises(KeyError):
        resolve_aircraft(icao, bada_path=fake_bada)


def test_unknown_type_message(fake_bada: Path) -> None:
    with pytest.raises(KeyError, match=r"Unable to resolve BADA mapping.*ICAO=ZZZZ"):
        resolve_aircraft("ZZZZ", engine_uid="01P21GE217", bada_path=fake_bada)


def test_missing_bada_dir_raises(tmp_path: Path) -> None:
    """A BADA root without the BADA4/BADA3 directories fails, as the
    performance step does, instead of giving ``bada_engine=None``."""
    with pytest.raises(FileNotFoundError, match="BADA4 path"):
        resolve_aircraft("A320", bada_path=tmp_path)
    (tmp_path / DEFAULT_BADA4_VERSION).mkdir()
    with pytest.raises(FileNotFoundError, match="BADA3 path"):
        resolve_aircraft("A320", bada_path=tmp_path)


def test_unreadable_bada4_xml_gives_no_engine_name(fake_bada: Path) -> None:
    """BADA directories without the model XML: the mapping still resolves."""
    r = resolve_aircraft("A320", bada_path=fake_bada)
    assert (r.bada_version, r.bada_model, r.bada_engine) == ("BADA4", "A320-214", None)


@pytest.mark.parametrize(
    ("series", "engine_uid", "expected"),
    [
        # Step (2) keeps a blank declared engine (``is not None`` test) ...
        ("A320-214", " ", ("", "operator")),
        ("A320-214", "nan", ("NAN", "operator")),
        # ... step (4) ignores it (truth test).
        (None, " ", ("1IA001", "MRR conservative")),
    ],
)
def test_blank_declared_engine_quirk(
    fake_bada: Path,
    series: str | None,
    engine_uid: str,
    expected: tuple[str, EngineSource],
) -> None:
    """Kept behaviour of the mapping chain (see ``BadaMapper.resolve``)."""
    r = resolve_aircraft("A320", series, engine_uid, bada_path=fake_bada)
    assert (r.emissions_engine_uid, r.emissions_engine_source) == expected


@pytest.mark.parametrize(
    ("icao", "series", "engine_uid"),
    [
        ("A320", None, None),
        ("A320", "A320-214", None),
        ("A320", None, "3CM026"),
        ("A342", None, None),
        ("A124", None, None),
        ("B738", None, "PW4060"),
        ("A30B", "A300B2 103", "3GE070"),
        ("B738", "B737 8AS", None),
    ],
)
def test_bada_type_wraps_resolver(
    fake_bada: Path, icao: str, series: str | None, engine_uid: str | None
) -> None:
    """``BADAPerformanceModelParams.bada_type`` gives the resolver's answer.

    Both go through ``BadaMapper.resolve``, so this checks the wrapping, not
    the mapping chain; ``test_resolver_matches_golden_outputs`` is the
    independent check against stored outputs.
    """
    params = BADAPerformanceModelParams()
    nb_eng, bada3, bada4, engine = params.bada_type(icao, series, engine_uid)
    r = resolve_aircraft(icao, series, engine_uid, params=params, bada_path=fake_bada)
    assert (nb_eng, engine) == (r.n_engine, r.emissions_engine_uid)
    expected_model = bada3 if r.bada_version == "BADA3" else bada4.strip()
    assert r.bada_model == expected_model


# ---------------------------------------------------------------------------
# Consistency with the pipeline
# ---------------------------------------------------------------------------


def _flight_id(record: dict[str, Any]) -> str:
    fid = record["flight_id"]
    return fid[0] if isinstance(fid, list) else fid


def _scalar(value: Any) -> Any:
    if isinstance(value, list):
        assert len({str(v) for v in value}) == 1, value
        return value[0]
    return value


def _golden_pairs() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(aircraft_properties, output record) of every golden output record."""
    pairs = []
    for in_path in sorted(GOLDEN_DIR.glob("*_input.json")):
        out_path = in_path.with_name(in_path.name.replace("_input", "_output"))
        inputs = json.loads(in_path.read_text(encoding="utf-8"))
        outputs = json.loads(out_path.read_text(encoding="utf-8"))
        props = {
            f["flight_information"]["flight_identification"]: f["flight_information"][
                "aircraft_properties"
            ]
            for f in inputs
        }
        pairs += [(props[_flight_id(o)], o) for o in outputs]
    return pairs


@pytest.mark.requires_bada
def test_resolver_matches_golden_outputs(bada: Path) -> None:
    """For every golden output record, the resolver gives the attrs the
    pipeline wrote (``bada_*`` only when the BADA model ran)."""
    pairs = _golden_pairs()
    assert len(pairs) > 50
    for props, out in pairs:
        r = resolve_aircraft(
            props["aircraft_type"],
            props.get("aircraft_version"),
            props.get("engine_uid"),
            bada_path=bada,
        )
        assert r.emissions_engine_uid == _scalar(out["engine_uid"]), props
        assert r.n_engine == _scalar(out["n_engine"]), props
        assert r.aircraft_type == _scalar(out["aircraft_type"]), props
        if out.get("bada_version") is not None:
            assert r.bada_version == _scalar(out["bada_version"]), props
            assert r.bada_model == _scalar(out["bada_code"]), props


@pytest.mark.requires_bada
@pytest.mark.slow
def test_resolver_matches_performance_step(bada: Path) -> None:
    """Run parsing, interpolation and the BADA performance step (ISA weather,
    no wind: the weather does not choose the aircraft) on the golden flights,
    also with an operator engine and a series, and compare the attrs.

    The step and the resolver share ``BadaMapper.resolve`` and
    ``_select_bada_model``, so this checks the wiring of the step (attrs,
    first attempt), not the mapping chain itself.
    """
    from pycontrails.physics.units import m_to_T_isa

    from pyneats.runners.flight import FlightRunner
    from pyneats.steps.parsing.neats_io import neats_json_to_flights
    from pyneats.steps.weather.weather_provider import FlightWithWeather

    class _PerformanceOnly(FlightRunner):
        def _climate_impact(self) -> Any:
            raise NotImplementedError

    golden = json.loads(
        (GOLDEN_DIR / "fleet_5_flights_input.json").read_text(encoding="utf-8")
    )
    operator = copy.deepcopy(golden[0])  # EAF2143, A320
    operator["flight_information"]["aircraft_properties"]["engine_uid"] = "3CM026"
    series = copy.deepcopy(golden[0])
    series["flight_information"]["aircraft_properties"]["aircraft_version"] = "A320-214"
    flights = neats_json_to_flights([*golden, operator, series])
    assert len(flights) == 7

    sources = set()
    for df in flights:
        runner = _PerformanceOnly(weather=None, source=df, bada_path=str(bada))  # type: ignore[arg-type]
        runner._parse_flight()._interpolate()
        f = runner.interpolated_flight
        assert f is not None
        f["u_wind"] = np.zeros(len(f))
        f["v_wind"] = np.zeros(len(f))
        f["air_temperature"] = m_to_T_isa(f["altitude"])
        f["specific_humidity"] = np.zeros(len(f))
        runner.flight_with_weather = FlightWithWeather.from_flight(f)
        runner._performance()
        assert runner.flight_with_performance is not None
        attrs = runner.flight_with_performance.attrs

        r = resolve_aircraft(
            df.attrs["aircraft_type"],
            df.attrs.get("aircraft_series"),
            df.attrs.get("engine_uid"),
            bada_path=bada,
        )
        assert attrs["engine_uid"] == r.emissions_engine_uid
        assert attrs["n_engine"] == r.n_engine
        assert attrs["aircraft_type"] == r.aircraft_type
        assert attrs["bada_version"] == r.bada_version
        assert attrs["bada_code"] == r.bada_model
        sources.add(r.emissions_engine_source)

    assert sources == {"MRR conservative", "operator"}
