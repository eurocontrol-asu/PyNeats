from __future__ import annotations

from enum import Enum
from typing import Any
from pyneats.steps.emissions.protocol import EmissionModel
from pyneats.steps.emissions.pycontrails_emissions import PyContrailsEmissionModel
from pyneats.steps.emissions.eurocontrol_emissions import EurocontrolEmissionModel
from pyneats.steps.emissions.dlr_emissions import DLREmissionModel

__all__ = ["EmissionModelType"]

class EmissionModelType(Enum):
    PYCONTRAILS = PyContrailsEmissionModel
    EUROCONTROL = EurocontrolEmissionModel
    DLR = DLREmissionModel

    def get(self, *args: Any, **kwargs: Any) -> EmissionModel:
        impl = self.value  # type: ignore[assignment]
        return impl(*args, **kwargs)  # type: ignore[misc]
