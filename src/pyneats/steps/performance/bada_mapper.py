"""BADA Aircraft Type Mapping Module

This module implements a hierarchical mapping system for resolving aircraft performance 
model types from BADA. It provides:

1. Mapping Resolution:
   Hierarchical resolution of BADA aircraft types using:
   - ICAO aircraft type designator
   - Aircraft series
   - Engine identifier
   The system follows a fallback chain to ensure maximum coverage.

2. Resolution Chain:
   a) Full match: ICAO + Series + Engine ID
   b) Partial match: ICAO + Series
   c) Partial match: ICAO + Engine ID
   d) Default engine lookup by ICAO, then retry (c)
   e) Fallback: ICAO only

3. Key Components:
   - BadaMappingPaths: Configuration for CSV mapping file locations
   - BadaMapper: Main resolver implementing the fallback chain
   - CSV caching system for performance optimization

"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache, cached_property
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd


@dataclass(frozen=True)
class BadaMappingPaths:
    """Paths to CSV files for BADA aircraft type mapping."""
    icao_series_engine: Path  # 1) triple key: ICAO + SERIES + ENGINE_ID
    icao_series: Path  # 2) double key: ICAO + SERIES
    icao_engine: Path  # 3) double key: ICAO + ENGINE_ID
    default_engine_by_icao: Path  # 4) default engine by ICAO
    icao_only: Path  # 5) fallback by ICAO only


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

    return df


def _load_df(path: Path, col_icao: str, col_series: str, col_engine: str) -> pd.DataFrame:
    return _read_csv_cached(str(path), col_icao, col_series, col_engine)


# ------ BadaMapper ------------------------------------------------------------


class BadaMapper:
    """Resolves BADA aircraft types using hierarchical CSV mappings."""
    
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
            self.paths.icao_series_engine, self.COL_ICAO, self.COL_SERIES, self.COL_ENGINE_ID
        )

    @cached_property
    def _df_icao_series(self) -> pd.DataFrame:
        return _load_df(self.paths.icao_series, self.COL_ICAO, self.COL_SERIES, self.COL_ENGINE_ID)

    @cached_property
    def _df_icao_engine(self) -> pd.DataFrame:
        return _load_df(self.paths.icao_engine, self.COL_ICAO, self.COL_SERIES, self.COL_ENGINE_ID)

    @cached_property
    def _df_default_engine_by_icao(self) -> pd.DataFrame:
        return _load_df(
            self.paths.default_engine_by_icao, self.COL_ICAO, self.COL_SERIES, self.COL_ENGINE_ID
        )

    @cached_property
    def _df_icao_only(self) -> pd.DataFrame:
        return _load_df(self.paths.icao_only, self.COL_ICAO, self.COL_SERIES, self.COL_ENGINE_ID)

    # --- Helpers -------------------------------------------------------------
    def _coerce_return(
        self, row: pd.Series, engine_id_override: Optional[str] = None
    ) -> Tuple[int, str, str, str]:
        missing = [
            c for c in (self.COL_NB_ENG, self.COL_BADA3, self.COL_BADA4) if c not in row.index
        ]
        if missing:
            raise KeyError(f"Row missing required columns: {missing}")

        nb_eng = int(row[self.COL_NB_ENG])
        bada3 = str(row[self.COL_BADA3])
        bada4 = str(row[self.COL_BADA4])

        if engine_id_override is not None:
            engine_id = engine_id_override
        else:
            engine_id = str(row[self.COL_ENGINE_ID]) if self.COL_ENGINE_ID in row.index else ""

        return nb_eng, bada3, bada4, engine_id

    def _find_one(self, df: pd.DataFrame, **filters: str) -> Optional[pd.Series]:
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

    def _default_engine_for_icao(self, icao: str) -> Optional[str]:
        row = self._find_one(self._df_default_engine_by_icao, **{self.COL_ICAO: icao})
        if row is None or self.COL_ENGINE_ID not in row.index:
            return None
        eng = str(row[self.COL_ENGINE_ID]).strip().upper()
        return eng or None

    # --- Public API ----------------------------------------------------------
    def bada_type(
        self,
        icao: str,
        series: Optional[str] = None,
        engine_id: Optional[str] = None,
    ) -> Tuple[int, str, str, str]:
        """
        Resolve BADA info using:
          1) (ICAO, SERIES, ENGINE_ID)
          2) (ICAO, SERIES)
          3) (ICAO, ENGINE_ID)
          4) Default ENGINE_ID by ICAO, then step (3)
          5) ICAO only

        Returns:
            (NB_ENG: int, BADA3: str, BADA4: str, ENGINE_ID: str)

        Raises:
            KeyError if nothing can be resolved.
        """
        if not icao:
            raise KeyError("ICAO is required")

        icao_n = icao.strip().upper()
        series_n = series.strip().upper() if series else None
        engine_n = engine_id.strip().upper() if engine_id else None

        engine_conservative = self._default_engine_for_icao(icao_n)

        # 1) triple key
        if series_n and engine_n:
            row = self._find_one(
                self._df_icao_series_engine,
                **{self.COL_ICAO: icao_n, self.COL_SERIES: series_n, self.COL_ENGINE_ID: engine_n},
            )
            if row is not None:
                return self._coerce_return(row, engine_id_override=engine_n)

        # 2) (ICAO, SERIES)
        if series_n:
            row = self._find_one(
                self._df_icao_series,
                **{self.COL_ICAO: icao_n, self.COL_SERIES: series_n},
            )
            if row is not None:
                if engine_n is not None:
                    return self._coerce_return(row, engine_id_override=engine_n)
                elif engine_conservative is not None:
                    return self._coerce_return(row, engine_id_override=engine_conservative)
                else:
                    return self._coerce_return(row)

        # 3) (ICAO, ENGINE_ID)
        if engine_n:
            row = self._find_one(
                self._df_icao_engine,
                **{self.COL_ICAO: icao_n, self.COL_ENGINE_ID: engine_n},
            )
            if row is not None:
                return self._coerce_return(row, engine_id_override=engine_n)

        # 4) default engine id by ICAO, then step (3)

        if engine_conservative:
            row = self._find_one(
                self._df_icao_engine,
                **{self.COL_ICAO: icao_n, self.COL_ENGINE_ID: engine_conservative},
            )
            if row is not None:
                return self._coerce_return(row, engine_id_override=engine_conservative)

        # 5) ICAO only
        row = self._find_one(self._df_icao_only, **{self.COL_ICAO: icao_n})
        if row is not None:
            if engine_conservative:
                return self._coerce_return(row, engine_id_override=engine_conservative)
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
