from __future__ import annotations
from dataclasses import dataclass, field
from importlib.resources import files
import pandas as pd
from typing import Final

from pyneats.core.constants import Q_FUEL
from pyneats.steps.performance.utils import load_bada_mapping

__all__ = ["DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW", "BADAPerformanceModelParams"]

DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW: Final[int] = 7

@dataclass(frozen=True)
class BADAPerformanceModelParams:
    true_air_speed_smoothing_window: int = DEFAULT_TRUE_AIR_SPEED_SMOOTHING_WINDOW
    bada_mapping_file: pd.DataFrame = field(default_factory=load_bada_mapping)
    bada4_config_path: str = str(files("pyBADA").joinpath("4.2.1")) + "/"
    bada3_config_path: str = str(files("pyBADA").joinpath("3.16")) + "/"
    q_fuel: float = Q_FUEL

    def bada_type(self, icao: str) -> tuple[int, str, str, str]:
        # expects a mapping df with columns: ICAO, NB_ENG, BADA3, BADA4, ENGINE_ID
        df: pd.DataFrame = self.bada_mapping_file
        cols = ["NB_ENG", "BADA3", "BADA4", "ENGINE_ID"]
        row = df.loc[df["ICAO"] == icao, cols]
        if row.empty:
            raise KeyError(f"No entry for ICAO '{icao}'")
        s = row.iloc[0]
        return int(s["NB_ENG"]), str(s["BADA3"]), str(s["BADA4"]), str(s["ENGINE_ID"])
