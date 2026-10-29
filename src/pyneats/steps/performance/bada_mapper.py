"""
BADA Aircraft Type Mapping Module

Implements a hierarchical mapping system for resolving aircraft performance model types from BADA.

Features
--------
- Hierarchical resolution of BADA aircraft types using ICAO, series, and engine ID
- Fallback chain for maximum coverage
- CSV caching system for performance optimization

Classes
-------
BadaMappingPaths
     Configuration for CSV mapping file locations.
BadaMapping
     Result of the fallback chain, with the source of the engine UID.
BadaMapper
     Main resolver implementing the fallback chain for BADA type resolution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property
from functools import lru_cache
from pathlib import Path
from typing import Literal

import pandas as pd


EngineSource = Literal["operator", "MRR conservative", "ECTL mapping row"]
"""Where the engine UID passed to the emissions step comes from.

- ``"operator"``: the value of the ``engine_uid`` flight attribute
  (the engine declared by the aircraft operator), stripped and upper-cased.
  The value is not checked: a blank value given with a series that matches
  an (ICAO, SERIES) row reaches the emissions step as ``""``, and ``"nan"``
  as ``"NAN"``, both labelled ``"operator"``.
- ``"MRR conservative"``: the engine of ``MRR_conservative_mapping.csv``
  for the ICAO type (no engine declared).
- ``"ECTL mapping row"``: the ``ENGINE_ID`` of the ECTL mapping row
  matched for the BADA model (no engine declared, ICAO type not in
  ``MRR_conservative_mapping.csv``).
"""


def _norm_series(s: str) -> str:
    """Remove all non-alphanumeric characters and upper-case — e.g. 'A321-213' → 'A321213'."""
    return re.sub(r"[^A-Z0-9]", "", s.upper())


@dataclass(frozen=True)
class BadaMappingPaths:
    """
    Paths to CSV files for BADA aircraft type mapping.

    Attributes
    ----------
    icao_series_engine : Path
        Path to CSV for ICAO + SERIES + ENGINE_ID mapping.
    icao_series : Path
        Path to CSV for ICAO + SERIES mapping.
    icao_engine : Path
        Path to CSV for ICAO + ENGINE_ID mapping.
    default_engine_by_icao : Path
        Path to CSV for default engine by ICAO.
    icao_only : Path
        Path to CSV for ICAO-only fallback mapping.
    """

    icao_series_engine: Path
    icao_series: Path
    icao_engine: Path
    default_engine_by_icao: Path
    icao_only: Path


@dataclass(frozen=True)
class BadaMapping:
    """
    Result of the BADA mapping chain for one aircraft.

    Attributes
    ----------
    nb_eng : int
        Number of engines (``NB_ENG`` of the matched row).
    bada3 : str
        BADA3 model code (``BADA3`` of the matched row).
    bada4 : str
        BADA4 model code (``BADA4`` of the matched row, ``"nan"`` when the
        row has none).
    engine_id : str
        Engine UID given to the emissions step (``engine_uid`` attribute).
    engine_source : EngineSource
        Where ``engine_id`` comes from.
    row_engine_id : str
        ``ENGINE_ID`` of the matched mapping row (``""`` when the file has
        no such column). It can differ from ``engine_id``.
    """

    nb_eng: int
    bada3: str
    bada4: str
    engine_id: str
    engine_source: EngineSource
    row_engine_id: str


# ------ Shared, cross-instance CSV cache -------------------------------------


@lru_cache(maxsize=64)
def _read_csv_cached(
    path_str: str, col_icao: str, col_series: str, col_engine: str
) -> pd.DataFrame:
    """Read + normalize a CSV and cache by (path, mtime)."""

    df = pd.read_csv(path_str)

    # Normalize the key columns if present
    for c in (col_icao, col_series, col_engine):
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip().str.upper()

    if col_series in df.columns:
        df[col_series] = df[col_series].str.replace(r"[^A-Z0-9]", "", regex=True)

    return df


def _load_df(
    path: Path, col_icao: str, col_series: str, col_engine: str
) -> pd.DataFrame:
    return _read_csv_cached(str(path), col_icao, col_series, col_engine)


# ------ BadaMapper ------------------------------------------------------------


class BadaMapper:
    """
    Resolves BADA aircraft types using hierarchical CSV mappings.

    Methods
    -------
    resolve(icao, series, engine_id)
        Resolve BADA info and the engine source using a fallback chain of keys.
    bada_type(icao, series, engine_id)
        Same chain as ``resolve``, returned as a tuple.
    """

    COL_ICAO = "ICAO"
    COL_SERIES = "ACFT_SERIES"
    COL_ENGINE_ID = "ENGINE_ID"
    COL_NB_ENG = "NB_ENG"
    COL_BADA3 = "BADA3"
    COL_BADA4 = "BADA4"

    def __init__(self, paths: BadaMappingPaths) -> None:
        self.paths = paths

    # CSV accessors — each property just pulls from the cross-instance cache
    @cached_property
    def _df_icao_series_engine(self) -> pd.DataFrame:
        return _load_df(
            self.paths.icao_series_engine,
            self.COL_ICAO,
            self.COL_SERIES,
            self.COL_ENGINE_ID,
        )

    @cached_property
    def _df_icao_series(self) -> pd.DataFrame:
        return _load_df(
            self.paths.icao_series, self.COL_ICAO, self.COL_SERIES, self.COL_ENGINE_ID
        )

    @cached_property
    def _df_icao_engine(self) -> pd.DataFrame:
        return _load_df(
            self.paths.icao_engine, self.COL_ICAO, self.COL_SERIES, self.COL_ENGINE_ID
        )

    @cached_property
    def _df_default_engine_by_icao(self) -> pd.DataFrame:
        return _load_df(
            self.paths.default_engine_by_icao,
            self.COL_ICAO,
            self.COL_SERIES,
            self.COL_ENGINE_ID,
        )

    @cached_property
    def _df_icao_only(self) -> pd.DataFrame:
        return _load_df(
            self.paths.icao_only, self.COL_ICAO, self.COL_SERIES, self.COL_ENGINE_ID
        )

    # --- Helpers -------------------------------------------------------------
    def _coerce_return(
        self,
        row: pd.Series,
        engine_id_override: str | None = None,
        engine_source: EngineSource = "ECTL mapping row",
    ) -> BadaMapping:
        missing = [
            c
            for c in (self.COL_NB_ENG, self.COL_BADA3, self.COL_BADA4)
            if c not in row.index
        ]
        if missing:
            raise KeyError(f"Row missing required columns: {missing}")

        nb_eng = int(row[self.COL_NB_ENG])
        bada3 = str(row[self.COL_BADA3])
        bada4 = str(row[self.COL_BADA4])

        row_engine_id = (
            str(row[self.COL_ENGINE_ID]) if self.COL_ENGINE_ID in row.index else ""
        )
        if engine_id_override is not None:
            engine_id = engine_id_override
        else:
            engine_id = row_engine_id
            engine_source = "ECTL mapping row"

        return BadaMapping(
            nb_eng=nb_eng,
            bada3=bada3,
            bada4=bada4,
            engine_id=engine_id,
            engine_source=engine_source,
            row_engine_id=row_engine_id,
        )

    def _find_one(self, df: pd.DataFrame, **filters: str) -> pd.Series | None:
        if df.empty:
            return None
        mask = pd.Series(True, index=df.index)
        for col, val in filters.items():
            if col not in df.columns:
                return None
            mask &= df[col] == val
        if not mask.any():
            return None
        return df.loc[mask].iloc[0]

    def _default_engine_for_icao(self, icao: str) -> str | None:
        row = self._find_one(self._df_default_engine_by_icao, **{self.COL_ICAO: icao})
        if row is None or self.COL_ENGINE_ID not in row.index:
            return None
        eng = str(row[self.COL_ENGINE_ID]).strip().upper()
        return eng or None

    # --- Public API ----------------------------------------------------------
    def bada_type(
        self,
        icao: str,
        series: str | None = None,
        engine_id: str | None = None,
    ) -> tuple[int, str, str, str]:
        """
        Resolve BADA info with the chain of ``resolve``.

        Returns:
            (NB_ENG: int, BADA3: str, BADA4: str, ENGINE_ID: str), where
            ENGINE_ID is the engine UID given to the emissions step
            (``BadaMapping.engine_id``).

        Raises:
            KeyError: If nothing can be resolved.
        """
        m = self.resolve(icao, series, engine_id)
        return m.nb_eng, m.bada3, m.bada4, m.engine_id

    def resolve(
        self,
        icao: str,
        series: str | None = None,
        engine_id: str | None = None,
    ) -> BadaMapping:
        """
        Resolve BADA info and the engine UID for emissions.

        The BADA row (NB_ENG, BADA3, BADA4) is the first match of:
          1) (ICAO, SERIES, ENGINE_ID)
          2) (ICAO, SERIES)
          3) (ICAO, ENGINE_ID)
          4) ICAO only

        The engine UID for emissions is the declared ENGINE_ID when one is
        given (``"operator"``). Without one, steps (2) and (4) take the
        default ENGINE_ID for the ICAO type from MRR_conservative_mapping.csv
        (``"MRR conservative"``), else the ENGINE_ID of the matched row
        (``"ECTL mapping row"``). The MRR default engine never selects the
        BADA row: it is not used as a key in steps (1) or (3).

        A blank declared engine (``" "``) is a quirk kept from the original
        chain: step (2) keeps it (``""``, ``"operator"``) because it tests
        ``is not None``, while step (4) ignores it because it tests truth.

        Returns:
            BadaMapping

        Raises:
            KeyError: If nothing can be resolved.
        """
        if not icao:
            raise KeyError("ICAO is required")

        icao_n = icao.strip().upper()
        series_n = _norm_series(series) if series else None
        engine_n = engine_id.strip().upper() if engine_id else None

        engine_conservative = self._default_engine_for_icao(icao_n)

        # 1) triple key
        if series_n and engine_n:
            row = self._find_one(
                self._df_icao_series_engine,
                **{
                    self.COL_ICAO: icao_n,
                    self.COL_SERIES: series_n,
                    self.COL_ENGINE_ID: engine_n,
                },
            )
            if row is not None:
                return self._coerce_return(
                    row, engine_id_override=engine_n, engine_source="operator"
                )

        # 2) (ICAO, SERIES)
        if series_n:
            row = self._find_one(
                self._df_icao_series,
                **{self.COL_ICAO: icao_n, self.COL_SERIES: series_n},
            )
            if row is not None:
                if engine_n is not None:
                    return self._coerce_return(
                        row, engine_id_override=engine_n, engine_source="operator"
                    )
                elif engine_conservative is not None:
                    return self._coerce_return(
                        row,
                        engine_id_override=engine_conservative,
                        engine_source="MRR conservative",
                    )
                else:
                    return self._coerce_return(row)

        # 3) (ICAO, ENGINE_ID)
        if engine_n:
            row = self._find_one(
                self._df_icao_engine,
                **{self.COL_ICAO: icao_n, self.COL_ENGINE_ID: engine_n},
            )
            if row is not None:
                return self._coerce_return(
                    row, engine_id_override=engine_n, engine_source="operator"
                )

        # 4) ICAO only
        row = self._find_one(self._df_icao_only, **{self.COL_ICAO: icao_n})
        if row is not None:
            if engine_n:
                return self._coerce_return(
                    row, engine_id_override=engine_n, engine_source="operator"
                )
            elif engine_conservative:
                return self._coerce_return(
                    row,
                    engine_id_override=engine_conservative,
                    engine_source="MRR conservative",
                )
            else:
                return self._coerce_return(row, engine_id_override=None)

        # Nothing worked
        tried = []
        if series_n and engine_n:
            tried.append(f"(ICAO={icao_n}, SERIES={series_n}, ENGINE_ID={engine_n})")
        if series_n:
            tried.append(f"(ICAO={icao_n}, SERIES={series_n})")
        if engine_n:
            tried.append(f"(ICAO={icao_n}, ENGINE_ID={engine_n})")
        if engine_conservative:
            tried.append(f"default ENGINE_ID {engine_conservative} for ICAO={icao_n}")
        tried.append(f"(ICAO={icao_n})")

        raise KeyError("Unable to resolve BADA mapping. Tried: " + " → ".join(tried))
