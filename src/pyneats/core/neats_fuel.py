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
from pyneats.core.neats_default_parameters import Q_FUEL_MAX
from pyneats.core.neats_default_parameters import Q_FUEL_MIN


__all__ = [
    "NEATSFuel",
]


def check_q_fuel(value: Any, source: str) -> float:
    """Return ``value`` as a float in J/kg, or raise if it is not plausible.

    A supplied q_fuel must lie within ``Q_FUEL_MIN``-``Q_FUEL_MAX`` (35-50 MJ/kg,
    in J/kg). The check exists to catch unit errors: a value in MJ/kg (e.g.
    43.05) is 1e6 times too small and would make the BADA fuel flow 1e6 times
    too large. ``source`` names where the value came from, for the message.

    Raises
    ------
    ValueError
        If ``value`` is not a number, or is NaN or outside the range.
    """
    q = float(value)
    if q != q:  # NaN
        raise ValueError(
            f"q_fuel from {source} is NaN; give a value in J/kg or leave it out "
            f"(None) to use the default."
        )
    if not Q_FUEL_MIN <= q <= Q_FUEL_MAX:
        raise ValueError(
            f"q_fuel = {q:g} J/kg from {source} is outside the plausible range "
            f"{Q_FUEL_MIN / 1e6:g}-{Q_FUEL_MAX / 1e6:g} MJ/kg. q_fuel must be in "
            f"J/kg: multiply a value in MJ/kg by 1e6."
        )
    return q


class NEATSFuel(SAFBlend):
    """
    SAF-like type (passes isinstance(..., SAFBlend) and truthy pct_blend) with
    configurable hydrogen content and/or q_fuel. Independent of pct_blend physics.

    Parameters
    ----------
    hydrogen_content : float, optional
        Hydrogen content in wt.% (percent by mass, e.g. 13.8 for Jet-A), the
        same scale as the AO field "percentage of hydrogen mass content". Not
        a fraction. Defaults to ``DEFAULT_HYDROGEN_CONTENT`` (13.79 wt.%).
    h_c_ratio : float, optional
        H/C ratio, dimensionless, atomic (molar): hydrogen atoms per carbon
        atom (Reg. (EU) 2018/2066 Annex IIIa §1(36)). Converted to wt.% with
        ``r * 1.008 / (12.011 + r * 1.008) * 100``; used only when
        ``hydrogen_content`` is None.
    q_fuel : float, optional
        PyNEATS input unit: J/kg of fuel (lower calorific value).
        The AO JSON field ``calorific_value`` is in MJ/kg of fuel.
        The NEATS application multiplies by 1e6 before calling PyNEATS.
        Values received here must already be in J/kg; do not convert again.
        Defaults to ``DEFAULT_Q_FUEL`` (42.8e6 J/kg). A supplied value outside
        ``Q_FUEL_MIN``-``Q_FUEL_MAX`` (35-50 MJ/kg) raises ``ValueError``
        (see ``check_q_fuel``).
    pct_blend_gate : float, optional
        Blend gate for SAFBlend compatibility.
    sulphur_content : float, optional
        Sulphur content, % by mass basis (Reg. (EU) 2018/2066 Annex IIIa §5(4) default);
        fraction vs percentage scale not defined by the AO schema. Stored
        only, not used in calculations.
    aromatics_content : float, optional
        Aromatics content, % by volume basis (Annex IIIa §5(4) default);
        fraction vs percentage scale not defined by the AO schema. Stored
        only, not used in calculations.
    naphthalene : float, optional
        Naphthalene content, % by volume basis (Annex IIIa §5(4) default);
        fraction vs percentage scale not defined by the AO schema. Stored
        only, not used in calculations.
    name : str, optional
        Name of the fuel.

    Notes
    -----
    Derived emission indices, all in kg per kg of fuel:

    - ``ei_co2`` is the pycontrails JetA value, independent of hydrogen content.
    - ``ei_h2o`` is the JetA value scaled by the resolved hydrogen content
      (wt.%) divided by 13.8 (JetA hydrogen content, wt.%).
    - ``ei_so2`` (and ``ei_sulphates`` derived from it) is the JetA value
      whatever ``sulphur_content`` is, so SO2 and sulphate outputs do not
      depend on the supplied sulphur (see docs/internal/pyneats_units_audit.md).
    """

    # Class defaults are fraction scale (see neats_default_parameters); values
    # supplied by the AO keep the AO scale, which the schema does not define.
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
            # Convert H/C atomic (molar) ratio to hydrogen *mass percent* using
            # atomic masses H = 1.008, C = 12.011 g/mol
            # (×100 to keep PyContrails' wt.% convention)
            h_wt_pct = (r * 1.008) / (12.011 + r * 1.008) * 100.0
        else:
            h_wt_pct = DEFAULT_HYDROGEN_CONTENT

        # --- Resolve q_fuel [J/kg, LHV]; already in J/kg on entry (see docstring)
        qf = check_q_fuel(q_fuel, "q_fuel") if q_fuel is not None else DEFAULT_Q_FUEL

        # --- Storing Optional Fuel Attributes from AOs, not used at this stage
        if aromatics_content is not None:
            object.__setattr__(self, "aromatics_content", aromatics_content)

        if sulphur_content is not None:
            object.__setattr__(self, "sulphur_content", sulphur_content)

        if naphthalene is not None:
            object.__setattr__(self, "naphthalene", naphthalene)

        # --- Derive dependent indices consistently [kg/kg fuel]
        # ei_co2 and ei_so2 are the JetA values; only ei_h2o follows h_wt_pct
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

        Values are passed through unconverted, so they must already be in the
        units of the constructor (``q_fuel`` in J/kg, ``hydrogen_content`` in
        wt.%). Only the key ``naphthalene`` is read; the airport-file path stores
        the value under ``naphtalene`` and the AO JSON path drops it, so a parsed
        naphthalene value is not picked up. Alternative keys are joined with
        ``or``, so an explicit 0.0 under the first key falls back to the second
        key, then to the default (see docs/internal/pyneats_units_audit.md).

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
