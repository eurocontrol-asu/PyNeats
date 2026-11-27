"""
Non-CO2 Scaling Schemes

Resolves the non-CO2 scaling of Method C (aCCF) and Method D (OpenAirClim),
selected by ``RunnerConfig.non_co2_scaling``:

- ``"accf_version"`` (default): the scaling used before 2026. Method C divides
  the raw aCCF regressions by ``ACCF_SCALE_*[accf_v]`` (local_accf.py) and the
  ATR by ``RF_BACKWARD_FACTOR`` (gwp.py); Method D applies no factor.
- ``"scaling_to_baseline_2026"``: one divisor per species and method
  (``SCALING_TO_BASELINE_2026_METHOD_C`` / ``_D`` in core/physics.py). For
  Method C it replaces both ``ACCF_SCALE_*[accf_v]`` and ``RF_BACKWARD_FACTOR``.

PMO uses the CH4 divisor unless the table has its own ``"PMO"`` entry.
Contrails are not scaled.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final
from typing import Literal
from typing import get_args

from pyneats.core.neats_default_parameters import NON_CO2_SCALINGS
from pyneats.core.physics import SCALING_TO_BASELINE_2026_METHOD_C
from pyneats.core.physics import SCALING_TO_BASELINE_2026_METHOD_D


__all__ = [
    "ACCF_VERSION_SCALING",
    "check_non_co2_scaling",
    "non_co2_scaling_divisors",
]

# The scaling used before 2026 (ACCF_SCALE_*[accf_v] and RF_BACKWARD_FACTOR)
ACCF_VERSION_SCALING: Final[str] = "accf_version"

_DIVISORS: Final[Mapping[str, Mapping[str, Mapping[str, float | None]]]] = {
    "scaling_to_baseline_2026": {
        "C": SCALING_TO_BASELINE_2026_METHOD_C,
        "D": SCALING_TO_BASELINE_2026_METHOD_D,
    },
}


def check_non_co2_scaling(scaling: str) -> None:
    """Raise ``ValueError`` if ``scaling`` is not a known non-CO2 scaling."""
    known = get_args(NON_CO2_SCALINGS)
    if scaling not in known:
        raise ValueError(
            f"Unknown non-CO2 scaling '{scaling}'; expected one of {list(known)}"
        )


def non_co2_scaling_divisors(
    scaling: str, method: Literal["C", "D"]
) -> dict[str, float] | None:
    """Return the divisors of ``scaling`` for ``method``, keyed by species.

    Args:
        scaling: Name of the non-CO2 scaling (``RunnerConfig.non_co2_scaling``).
        method: ``"C"`` (aCCF) or ``"D"`` (OpenAirClim).

    Returns:
        ``None`` for ``"accf_version"`` (the step applies its own factors);
        otherwise ``{"O3", "CH4", "PMO", "H2O"}`` divisors; PMO is the CH4
        value when the table has no ``"PMO"`` entry.

    Raises:
        ValueError: ``scaling`` is unknown, or one of its divisors is not set
            yet (None) or is not a positive number.
    """
    check_non_co2_scaling(scaling)
    if scaling == ACCF_VERSION_SCALING:
        return None

    table = _DIVISORS[scaling][method]
    not_set = sorted(sp for sp, v in table.items() if v is None)
    if not_set:
        raise ValueError(
            f"Non-CO2 scaling '{scaling}' has no Method {method} divisor yet for "
            f"{not_set} (set them in pyneats/core/physics.py)"
        )
    divisors = {sp: float(v) for sp, v in table.items() if v is not None}
    bad = sorted(sp for sp, v in divisors.items() if not v > 0.0)
    if bad:
        raise ValueError(
            f"Non-CO2 scaling '{scaling}' Method {method} divisors must be "
            f"positive; got {[(sp, divisors[sp]) for sp in bad]}"
        )
    divisors.setdefault("PMO", divisors["CH4"])
    return divisors
