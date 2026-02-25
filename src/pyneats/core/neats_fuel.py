"""
Custom Fuel Class for NEATS

This module defines NEATSFuel, a custom fuel class inheriting from PyContrails' SAFBlend,
with configurable hydrogen content and q_fuel, and utility methods for attribute-based construction.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pycontrails.core.fuel import Fuel
from pycontrails.core.fuel import JetA
from pycontrails.core.fuel import SAFBlend

from pyneats.core.neats_default_parameters import DEFAULT_AROMATICS_CONTENT
from pyneats.core.neats_default_parameters import DEFAULT_HYDROGEN_CONTENT
from pyneats.core.neats_default_parameters import DEFAULT_NAPHTHALEN_CONTENT
from pyneats.core.neats_default_parameters import DEFAULT_Q_FUEL
from pyneats.core.neats_default_parameters import DEFAULT_SULPHUR_CONTENT


__all__ = [
    "NEATSFuel",
]


class NEATSFuel(SAFBlend):
    """
    SAF-like type (passes isinstance(..., SAFBlend) and truthy pct_blend) with
    configurable hydrogen content and/or q_fuel. Independent of pct_blend physics.

    Parameters
    ----------
    hydrogen_content : float, optional
        Hydrogen content in weight percent (wt.% H).
    h_c_ratio : float, optional
        Atomic H/C ratio.
    q_fuel : float, optional
        Lower heating value (J/kg).
    pct_blend_gate : float, optional
        Blend gate for SAFBlend compatibility.
    sulphur_content : float, optional
        Sulphur content (not used in calculations).
    aromatics_content : float, optional
        Aromatics content (not used in calculations).
    naphthalene : float, optional
        Naphthalene content (not used in calculations).
    name : str, optional
        Name of the fuel.
    """

    aromatics_content: float = (
        DEFAULT_AROMATICS_CONTENT  # default value - Not used in calculations
    )
    sulphur_content: float = (
        DEFAULT_SULPHUR_CONTENT  # default value - Not used in calculations
    )
    naphthalene: float = (
        DEFAULT_NAPHTHALEN_CONTENT  # default value - Not used in calculations
    )

    def __init__(
        self,
        *,
        hydrogen_content: float | None = None,  # wt.% H (e.g., 13.8 for Jet-A)
        h_c_ratio: float | None = None,  # atomic H/C ratio r
        q_fuel: float | None = None,  # J/kg (LHV)
        pct_blend_gate: float = 1e-12,  # tiny, but needed for PyContrails gate
        sulphur_content: float | None = None,
        aromatics_content: float | None = None,
        naphthalene: float | None = None,
        name: str = "NEATS Fuel (custom)",
    ) -> None:
        # pylint: disable=super-init-not-called
        # Intent: bypass SAFBlend.__init__ and directly initialise via Fuel
        base = JetA()

        # --- Resolve hydrogen content (wt.%)
        if hydrogen_content is not None:
            h_wt_pct = float(hydrogen_content)
        elif h_c_ratio is not None:
            r = float(h_c_ratio)
            # Convert H/C atomic ratio to hydrogen *mass percent*
            # (×100 to keep PyContrails' convention)
            h_wt_pct = (r * 1.008) / (12.011 + r * 1.008) * 100.0
        else:
            h_wt_pct = DEFAULT_HYDROGEN_CONTENT

        # --- Resolve q_fuel
        qf = float(q_fuel) if q_fuel is not None else DEFAULT_Q_FUEL

        # --- Storing Optional Fuel Attributes from AOs, not used at this stage
        if aromatics_content is not None:
            object.__setattr__(self, "aromatics_content", aromatics_content)

        if sulphur_content is not None:
            object.__setattr__(self, "sulphur_content", sulphur_content)

        if naphthalene is not None:
            object.__setattr__(self, "naphthalene", naphthalene)

        # --- Derive dependent indices consistently
        ei_co2 = base.ei_co2
        ei_h2o = base.ei_h2o * (h_wt_pct / base.hydrogen_content)
        ei_so2 = base.ei_so2
        ei_sulphates = ei_so2 / 0.98 * 0.02
        ei_oc = base.ei_oc

        # --- Initialize frozen base dataclass in one shot
        # pylint: disable=non-parent-init-called
        Fuel.__init__(
            self,
            fuel_name=name,
            q_fuel=qf,
            hydrogen_content=h_wt_pct,
            ei_co2=ei_co2,
            ei_h2o=ei_h2o,
            ei_so2=ei_so2,
            ei_sulphates=ei_sulphates,
            ei_oc=ei_oc,
        )

        # set the blend gate so that downstream code treats as SAFBlend
        object.__setattr__(
            self, "pct_blend", pct_blend_gate if pct_blend_gate > 0.0 else 1e-12
        )

    @staticmethod
    def _to_scalar(val: Any) -> Any:
        """
        Convert list/array to scalar if needed.

        When loading from JSON, fuel properties may be stored as arrays (columns)
        rather than scalars (attrs) due to FlightView.to_dict() merging behavior.
        This extracts the first element if the value is a list/array.

        Parameters
        ----------
        val : Any
            Value to convert.

        Returns
        -------
        Any
            Scalar value or original value if not a sequence.
        """
        if val is None:
            return None
        if isinstance(val, (list, tuple)) and len(val) > 0:
            return val[0]
        # Handle numpy arrays
        if (
            hasattr(val, "__len__")
            and hasattr(val, "__getitem__")
            and not isinstance(val, str)
        ):
            try:
                if len(val) > 0:
                    return val[0]
            except TypeError:
                pass
        return val

    @classmethod
    def from_attrs(cls, attrs: Mapping[str, Any]) -> NEATSFuel:
        """
        Build a NEATSFuel instance from a generic attributes dictionary.

        Accepts both None and missing values; applies NEATS defaults.
        Handles the case where fuel properties are stored as arrays (from column serialization)
        by extracting the first element.

        Parameters
        ----------
        attrs : Mapping[str, Any]
            Attributes dictionary containing fuel properties.

        Returns
        -------
        NEATSFuel
            Constructed NEATSFuel instance.
        """
        return cls(
            q_fuel=cls._to_scalar(attrs.get("q_fuel")),
            hydrogen_content=cls._to_scalar(attrs.get("hydrogen_content")),
            h_c_ratio=cls._to_scalar(attrs.get("h_c_ratio")),
            sulphur_content=cls._to_scalar(
                attrs.get("sulphur_content") or attrs.get("sulfur_content")
            ),
            aromatics_content=cls._to_scalar(
                attrs.get("aromatics_content") or attrs.get("aromatic_content")
            ),
            naphthalene=cls._to_scalar(attrs.get("naphthalene")),
        )
