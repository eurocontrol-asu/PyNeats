"""
Aircraft Resolution Module

Tells, without running a flight, which BADA model and which engine PyNEATS
uses for an aircraft: the BADA model of the performance step, and the engine
UID that the emissions step gives to pycontrails (``attrs["engine_uid"]``).

The performance step (``BADAPerformanceModel._resolve_bada_adapter`` and its
BADA3 retry) uses the same two pieces: the mapping chain of
``BadaMapper.resolve`` (through ``bada_type``) and the BADA4/BADA3 rule of
``_select_bada_model``. So the answer is the one a flight gets.

Classes
-------
ResolvedAircraft
     BADA model and engines resolved for an aircraft.

Functions
---------
resolve_aircraft
     Resolve the BADA model and the engines for an ICAO type.
"""

from __future__ import annotations

import dataclasses
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Literal

from pyneats.steps.performance.bada_mapper import BadaMapper
from pyneats.steps.performance.bada_mapper import EngineSource


if TYPE_CHECKING:
    from pyneats.steps.performance.bada_model import BADAPerformanceModelParams


__all__ = [
    "EngineSource",
    "ResolvedAircraft",
    "resolve_aircraft",
]


@dataclass(frozen=True)
class ResolvedAircraft:
    """
    BADA model and engines resolved for an aircraft.

    Attributes
    ----------
    bada_version : {"BADA4", "BADA3"}
        BADA family of the performance model (``attrs["bada_version"]``).
    bada_release : str
        Release of the BADA files, i.e. the name of the BADA directory
        (e.g. ``"4.2.1"``, ``"3.16"``).
    bada_model : str
        BADA model code (BADA4 model or BADA3 file id, ``attrs["bada_code"]``),
        e.g. ``"A320-214"``.
    bada_engine : str or None
        BADA4: the ``<engine>`` of the model XML, e.g. ``"CFM56-5B4/P SAC"``
        (None when the XML cannot be read, which the performance step would
        then also fail to load). BADA3: None.
    bada_engine_uid : str
        ``ENGINE_ID`` of the ECTL mapping row matched for the BADA model.
    n_engine : int
        Number of engines (``NB_ENG`` of the mapping row, ``attrs["n_engine"]``).
    aircraft_type : str
        Aircraft type used by the emissions step (``attrs["aircraft_type"]``):
        the ICAO type as given.
    emissions_engine_uid : str
        Engine UID passed to pycontrails (``attrs["engine_uid"]``).
    emissions_engine_source : {"operator", "MRR conservative", "ECTL mapping row"}
        Where ``emissions_engine_uid`` comes from (see ``EngineSource``).
    """

    bada_version: Literal["BADA4", "BADA3"]
    bada_release: str
    bada_model: str
    bada_engine: str | None
    bada_engine_uid: str
    n_engine: int
    aircraft_type: str
    emissions_engine_uid: str
    emissions_engine_source: EngineSource


def _normalize_code_or_none(code: str | None) -> str | None:
    if code is None:
        return None
    s = str(code).strip()
    if not s:
        return None
    # handle common "nan" strings
    if s.lower() in {"nan", "none", "null"}:
        return None
    return s


def _select_bada_model(
    bada3: str, bada4: str | None, force_bada3: bool = False
) -> tuple[Literal["BADA4", "BADA3"], str]:
    """BADA family and model code of a mapping row.

    The one rule for both ``resolve_aircraft`` and the performance step:
    BADA3 when the row has no BADA4 model or when ``force_bada3`` is True,
    else BADA4 (the BADA4 code is stripped, the BADA3 code is kept as is).
    """
    bada4_code = _normalize_code_or_none(bada4)
    if bada4_code is None or force_bada3:
        return "BADA3", bada3
    return "BADA4", bada4_code


@lru_cache(maxsize=256)
def _bada4_engine_name(model_dir: str, bada4_code: str) -> str | None:
    """``<engine>`` of a BADA4 model XML; None when it cannot be read."""
    xml_path = Path(model_dir) / bada4_code / f"{bada4_code}.xml"
    try:
        root = ET.parse(xml_path).getroot()
    except (OSError, ET.ParseError, ValueError):
        return None
    engine = root.findtext("engine")
    if engine is None:
        return None
    return engine.strip() or None


def _resolve_with_mapper(
    mapper: BadaMapper,
    icao: str,
    series: str | None,
    engine_uid: str | None,
    bada4_path: Path,
    bada3_path: Path,
    force_bada3: bool = False,
) -> ResolvedAircraft:
    """Resolve with an explicit mapper and BADA directories.

    The mapping row comes from ``BadaMapper.resolve`` (the chain behind
    ``bada_type``, which the performance step calls) and the BADA family from
    ``_select_bada_model`` (the rule the performance step applies).

    Raises
    ------
    KeyError
        If the mapping cannot resolve the aircraft (see ``BadaMapper.resolve``).
    """
    m = mapper.resolve(icao, series, engine_uid)
    version, model = _select_bada_model(m.bada3, m.bada4, force_bada3)
    if version == "BADA3":
        release, engine = bada3_path.name, None
    else:
        release, engine = bada4_path.name, _bada4_engine_name(str(bada4_path), model)

    return ResolvedAircraft(
        bada_version=version,
        bada_release=release,
        bada_model=model,
        bada_engine=engine,
        bada_engine_uid=m.row_engine_id,
        n_engine=m.nb_eng,
        aircraft_type=icao,
        emissions_engine_uid=m.engine_id,
        emissions_engine_source=m.engine_source,
    )


def resolve_aircraft(
    icao: str,
    series: str | None = None,
    engine_uid: str | None = None,
    *,
    bada_path: str | Path | None = None,
    params: BADAPerformanceModelParams | None = None,
    force_bada3: bool = False,
) -> ResolvedAircraft:
    """
    Resolve the BADA model and the engines for an aircraft, without a flight.

    The answer is the one the performance step gives a flight with these
    ``aircraft_type``, ``aircraft_series`` and ``engine_uid`` attributes on
    its first attempt. A flight whose BADA4 attempt fails is retried with
    BADA3 (``force_bada3=True`` shows that model); the engine UID and the
    number of engines are the same in both cases.

    Parameters
    ----------
    icao : str
        ICAO aircraft type designator, e.g. ``"A320"``.
    series : str, optional
        Aircraft series, e.g. ``"A320-214"``.
    engine_uid : str, optional
        Engine UID declared by the aircraft operator (ICAO EDB UID).
    bada_path : str or Path, optional
        Root of the BADA3 and BADA4 files, as ``bada_path`` of the runners.
        Used for the BADA4 engine name and the BADA release. Default: the
        roots of ``params``.
    params : BADAPerformanceModelParams, optional
        Performance parameters (mapping files, BADA versions and roots).
        Default: ``BADAPerformanceModelParams()``.
    force_bada3 : bool, default False
        Give the BADA3 model, as the BADA3 retry of the performance step.

    Returns
    -------
    ResolvedAircraft

    Raises
    ------
    FileNotFoundError
        If the BADA4 or the BADA3 directory (root / version) does not exist,
        as the performance step does.
    KeyError
        If ``icao`` is empty or the mapping cannot resolve the aircraft.

    Examples
    --------
    >>> r = resolve_aircraft("A320", bada_path="/path/to/bada")  # doctest: +SKIP
    >>> r.bada_model, r.bada_engine, r.bada_engine_uid  # doctest: +SKIP
    ('A320-214', 'CFM56-5B4/P SAC', '3CM026')
    >>> r.emissions_engine_uid, r.emissions_engine_source  # doctest: +SKIP
    ('1IA001', 'MRR conservative')
    """
    if params is None:
        # Local import: bada_model imports this module.
        from pyneats.steps.performance.bada_model import BADAPerformanceModelParams

        params = BADAPerformanceModelParams()
    if bada_path is not None:
        params = dataclasses.replace(
            params, bada4_root_path=str(bada_path), bada3_root_path=str(bada_path)
        )

    bada4_path = Path(params.bada4_root_path).joinpath(params.bada4_version)
    bada3_path = Path(params.bada3_root_path).joinpath(params.bada3_version)
    for name, path in (("BADA4", bada4_path), ("BADA3", bada3_path)):
        if not path.is_dir():
            raise FileNotFoundError(
                f"{name} path '{path}' does not exist or is not a directory"
            )

    return _resolve_with_mapper(
        params.mapper,
        icao,
        series,
        engine_uid,
        bada4_path=bada4_path,
        bada3_path=bada3_path,
        force_bada3=force_bada3,
    )
