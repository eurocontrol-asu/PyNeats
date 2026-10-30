"""Point-by-point comparison of a pipeline output with its golden record.

The golden tests (``test_fleet_pipeline.py``, ``test_pipeline.py`` and the
success tests in ``test_cases_pipeline.py``) compare the serialised flight
(``FlightView.to_dict()``) with the record stored in
``tests/data/golden/*_output.json``. Both are dicts with the same layout: one
list per data column (one value per waypoint) and one scalar per flight-level
attribute (``total_*``, ``n_engine``, ``q_fuel``, ...), plus the nested
``climate_impact`` payload.

Rules (:func:`assert_matches_golden`):

- Same set of keys. Same length for every column.
- Strings, integers (``time``, ``waypoint``, ``contrail_age``, ``n_engine``),
  booleans and ``None``: exact, and of the same kind on both sides.
- Floats: the NaN/inf pattern must be exact (NaN where the golden has NaN,
  finite where it is finite). Finite values must satisfy
  ``|actual - expected| <= atol + rtol * |expected|`` with

  - per-point columns: ``atol = atol_fraction * rtol * scale``, where
    ``scale`` is the median of the non-zero finite ``|expected|`` of the
    column. The values of one column share a unit, and the noise of a
    computed value follows the typical size of the column, not the value
    itself: without a floor, a column that crosses zero or holds
    near-cancelled values fails on noise at its smallest points. The median,
    not the maximum, sets the scale, so that one large value (``ef`` spans
    seven orders of magnitude) does not hide changes at the other points.
    ``ATOL_FRACTION = 0.1`` (the default) stays small next to ``rtol``: a
    change of ``2 * rtol`` to a whole column fails at every point above
    ``0.1 * scale``.
  - flight-level scalars: ``atol = 0``, purely relative, so an expected 0
    must be exactly 0. This is stricter than the payload check (where an
    expected 0 accepts up to ``rtol`` in absolute terms) on purpose: a
    flight-level 0 comes from an empty or zero input (no sulphur, no
    contrail), which is exactly 0 on every machine.

- ``loose`` columns (FlightRunner contrail columns, see ``test_pipeline.py``):
  same length, kinds and NaN pattern; values within ``fraction *
  max|expected column|``, no relative part.
- ``climate_impact``: :func:`tests.conftest.assert_climate_payload_equal`
  at the same ``rtol``.

All failing keys are reported in one message, each with the first failing
index, the expected and actual values, the relative difference and the number
of failing points.

Known risk (not measured): the FleetRunner and TC tests compare the contrail
columns (``ef``, ``rf_*_mean``, ``contrail_age``, ...) and the Contrails
payload at ``rtol`` too. They are bit-identical on the machine that made the
goldens, but contrail evolution amplifies input noise (FlightRunner vs
FleetRunner: 1.9e-6 of the scale in the CoCiP inputs gives up to 28 % at single
points). If another machine or library build makes these tests fail only on
contrail values, pass the FlightRunner contrail treatment (``loose`` and
``CONTRAIL_RTOL`` in ``test_pipeline.py``) there too, rather than loosening
``GOLDEN_RTOL``.
"""

from __future__ import annotations

import math
from collections.abc import Collection
from collections.abc import Mapping
from typing import Any

import numpy as np

from tests.conftest import assert_climate_payload_equal


__all__ = ["ATOL_FRACTION", "GOLDEN_RTOL", "assert_matches_golden"]

# Relative tolerance of the golden comparison (G-2, decided 2026-10-30). On the
# machine that generated the goldens the output is bit-identical; 1e-5 leaves
# room for float noise between machines and library builds.
GOLDEN_RTOL = 1e-5

# Absolute floor of a per-point column, as a fraction of ``rtol * scale``
# (see the module docstring).
ATOL_FRACTION = 0.1

_PAYLOAD_KEY = "climate_impact"


def _rel(actual: float, expected: float) -> float:
    """Relative difference, ``inf`` when ``expected`` is 0 and ``actual`` is not."""
    diff = abs(actual - expected)
    if diff == 0:
        return 0.0
    return diff / abs(expected) if expected != 0 else math.inf


def _kind(value: Any) -> str:
    """Comparison kind of one value: 'bool', 'int', 'float', 'str' or 'other'."""
    if isinstance(value, bool | np.bool_):
        return "bool"
    if isinstance(value, int | np.integer):
        return "int"
    if isinstance(value, float | np.floating):
        return "float"
    if isinstance(value, str):
        return "str"
    return "other"


def _column_scale(e: np.ndarray) -> float:
    """Median of the non-zero finite ``|e|`` (0 if there is none)."""
    nonzero = np.abs(e[np.isfinite(e) & (e != 0)])
    return float(np.median(nonzero)) if nonzero.size else 0.0


def _compare_floats(
    key: str, actual: list[Any], expected: list[Any], rtol: float, atol: float
) -> str | None:
    """Compare two float columns: exact NaN/inf pattern, ``atol + rtol*|e|``."""
    a = np.asarray(actual, dtype=float)
    e = np.asarray(expected, dtype=float)
    a_fin = np.isfinite(a)
    e_fin = np.isfinite(e)
    # Non-finite values (NaN, +inf, -inf) must match exactly.
    nonfinite_ok = np.where(e_fin, a_fin, (a == e) | (np.isnan(a) & np.isnan(e)))
    both = a_fin & e_fin
    with np.errstate(invalid="ignore"):
        close = np.abs(a - e) <= atol + rtol * np.abs(e)
    ok = nonfinite_ok & (~both | close)
    if ok.all():
        return None

    bad = np.flatnonzero(~ok)
    i = int(bad[0])
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.abs(a - e) / np.abs(e)
    rel_both = rel[both & ~ok]
    max_rel = f"{np.max(rel_both):.3e}" if rel_both.size else "n/a"
    return (
        f"{key}: {bad.size}/{e.size} points outside rtol={rtol:g}, atol={atol:.3e} "
        f"(NaN pattern exact); first at index {i}: expected {float(e[i])!r}, actual "
        f"{float(a[i])!r}, rel diff {_rel(a[i], e[i]):.3e}; max rel diff {max_rel}"
    )


def _compare_column(
    key: str,
    actual: list[Any],
    expected: list[Any],
    rtol: float,
    atol_fraction: float,
    loose: float | None,
) -> str | None:
    """Return a failure message for one per-point column, or None if it matches."""
    if len(actual) != len(expected):
        return f"{key}: length {len(actual)} != expected {len(expected)}"
    if not expected:
        return None

    exp_kinds = {_kind(v) for v in expected}
    act_kinds = {_kind(v) for v in actual}
    if act_kinds != exp_kinds:
        return f"{key}: value kinds {sorted(act_kinds)} != expected {sorted(exp_kinds)}"

    if loose is not None and exp_kinds <= {"float", "int"}:
        e = np.asarray(expected, dtype=float)
        fin = np.isfinite(e)
        scale = float(np.max(np.abs(e[fin]))) if fin.any() else 0.0
        return _compare_floats(key, actual, expected, 0.0, loose * scale)

    if exp_kinds != {"float"}:
        # Integers, strings, booleans, None: exact.
        bad = [i for i, (a, e) in enumerate(zip(actual, expected)) if a != e]
        if not bad:
            return None
        i = bad[0]
        return (
            f"{key}: {len(bad)}/{len(expected)} points differ (exact); first at "
            f"index {i}: expected {expected[i]!r}, actual {actual[i]!r}"
        )

    scale = _column_scale(np.asarray(expected, dtype=float))
    return _compare_floats(key, actual, expected, rtol, atol_fraction * rtol * scale)


def _compare_scalar(key: str, actual: Any, expected: Any, rtol: float) -> str | None:
    """Return a failure message for one flight-level value, or None if it matches."""
    ka, ke = _kind(actual), _kind(expected)
    if ka != ke:
        return f"{key}: expected {expected!r} ({ke}), actual {actual!r} ({ka})"
    if ke != "float":
        return (
            None
            if actual == expected
            else (f"{key}: expected {expected!r}, actual {actual!r} (exact)")
        )
    if not (math.isfinite(expected) and math.isfinite(actual)):
        same = actual == expected or (math.isnan(actual) and math.isnan(expected))
        return None if same else f"{key}: expected {expected!r}, actual {actual!r}"
    rel = _rel(actual, expected)
    if rel <= rtol:
        return None
    return (
        f"{key}: expected {expected!r}, actual {actual!r}, rel diff {rel:.3e} "
        f"> rtol={rtol:g}"
    )


def assert_matches_golden(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    rtol: float = GOLDEN_RTOL,
    atol_fraction: float = ATOL_FRACTION,
    loose: Mapping[str, float] | None = None,
    skip: Collection[str] = (),
    label: str = "",
) -> None:
    """Assert a serialised flight matches its golden record.

    Args:
        actual: ``FlightView.to_dict()`` of the pipeline output.
        expected: The golden record, as loaded from the ``*_output.json`` file.
        rtol: Relative tolerance for floats (see the module docstring).
        atol_fraction: Absolute floor of a per-point float column, as a
            fraction of ``rtol`` times the median non-zero ``|expected|``.
        loose: Columns compared only within ``fraction * max|expected
            column|`` (length, kinds and NaN pattern still exact).
        skip: Keys whose values are not compared (they must still be present).
            ``"climate_impact"`` in ``skip`` leaves the payload to the caller.
        label: Prefix of the failure message (case, flight).

    Raises:
        AssertionError: Listing every key that does not match.
    """
    loose = loose or {}
    prefix = f"{label}: " if label else ""
    actual_keys, expected_keys = set(actual), set(expected)
    if actual_keys != expected_keys:
        raise AssertionError(
            f"{prefix}keys differ from the golden output (extra "
            f"{sorted(actual_keys - expected_keys)}, missing "
            f"{sorted(expected_keys - actual_keys)})"
        )

    failures: list[str] = []
    for key in sorted(expected_keys - set(skip) - {_PAYLOAD_KEY}):
        a, e = actual[key], expected[key]
        if isinstance(e, list) or isinstance(a, list):
            if not (isinstance(e, list) and isinstance(a, list)):
                failures.append(
                    f"{key}: expected {type(e).__name__}, actual {type(a).__name__}"
                )
                continue
            msg = _compare_column(key, a, e, rtol, atol_fraction, loose.get(key))
        else:
            msg = _compare_scalar(key, a, e, rtol)
        if msg is not None:
            failures.append(msg)

    if _PAYLOAD_KEY in expected_keys and _PAYLOAD_KEY not in skip:
        try:
            assert_climate_payload_equal(
                actual[_PAYLOAD_KEY], expected[_PAYLOAD_KEY], rtol=rtol
            )
        except AssertionError as exc:
            failures.append(f"{_PAYLOAD_KEY}.{exc}")

    if failures:
        raise AssertionError(
            f"{prefix}{len(failures)} value(s) differ from the golden output:\n  "
            + "\n  ".join(failures)
        )
