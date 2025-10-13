from __future__ import annotations

from typing import Optional

from pycontrails.core.fuel import Fuel, JetA, SAFBlend

__all__ = [
    "NEATSFuel",
]

class NEATSFuel(SAFBlend):
    """
    SAF-like type (passes isinstance(..., SAFBlend) and truthy pct_blend) with
    configurable hydrogen content and/or q_fuel. Independent of pct_blend physics.
    """
    
    def __init__(
        self,
        *,
        hydrogen_content: Optional[float] = None,  # wt.% H (e.g., 13.8 for Jet-A)
        h_c_ratio: Optional[float] = None,         # atomic H/C ratio r
        q_fuel: Optional[float] = None,            # J/kg (LHV)
        pct_blend_gate: float = 1e-12,             # tiny, but truthy for PyContrails gate
        sulphur_free: bool = False,                # set True to zero SOx if you want SAF-like S=0
        name: str = "NEATS Fuel (custom)",
    ) -> None:
        # pylint: disable=super-init-not-called
        # Intentional: we don't call SAFBlend.__init__ because it derives fields from pct_blend.
        # We fully initialize the frozen Fuel base directly to keep our custom physics.


        base = JetA()

        # --- Resolve hydrogen content (wt.%) with precedence: hydrogen_content > h_c_ratio > default
        if hydrogen_content is not None:
            h_wt_pct = float(hydrogen_content)
        elif h_c_ratio is not None:
            r = float(h_c_ratio)
            # Convert H/C atomic ratio to hydrogen *mass percent* (×100 to keep PyContrails' convention)
            h_wt_pct = (r * 1.008) / (12.011 + r * 1.008) * 100.0
        else:
            h_wt_pct = base.hydrogen_content  # Jet-A default (~13.8)

        # --- Resolve q_fuel
        qf = float(q_fuel) if q_fuel is not None else base.q_fuel

        # --- Derive dependent indices consistently
        ei_co2 = base.ei_co2
        ei_h2o = base.ei_h2o * (h_wt_pct / base.hydrogen_content)

        if sulphur_free:
            ei_so2 = 0.0
            ei_sulphates = 0.0
        else:
            ei_so2 = base.ei_so2
            ei_sulphates = ei_so2 / 0.98 * 0.02

        ei_oc = base.ei_oc

        # --- Initialize frozen base dataclass in one shot (no post-mutation)
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

        # --- Trip PyContrails' gate: isinstance(..., SAFBlend) and truthy pct_blend
        # (bypass frozen guard)
        object.__setattr__(self, "pct_blend", pct_blend_gate if pct_blend_gate > 0.0 else 1e-12)
