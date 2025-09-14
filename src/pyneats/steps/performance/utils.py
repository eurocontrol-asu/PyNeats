from __future__ import annotations
import pandas as pd

__all__ = ["load_bada_mapping"]

def load_bada_mapping() -> pd.DataFrame:
    # Local import keeps module import fast
    import pkg_resources
    path = pkg_resources.resource_filename("pyneats.ressources", "mapping_bada.csv")
    return pd.read_csv(path)
