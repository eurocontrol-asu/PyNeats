"""The climate constants in physics.py equal the MRV specification (decision C.16).

docs/explanation/mrv-specification.md (Section 3.7.1) is the reference for the
CO2 AGWP coefficients C(H) and the seconds per year s_yr. These tests read the
values from the specification, so a change on one side only fails here.
"""

import re
from pathlib import Path

import pytest

from pyneats.core.physics import CO2_AGWP_COEFF_WM2YR_PER_KG
from pyneats.core.physics import SECONDS_PER_YEAR
from pyneats.steps.climate_metrics.gwp import GWPParams


SPEC = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "explanation"
    / "mrv-specification.md"
)


@pytest.fixture(scope="module")
def spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


def test_seconds_per_year_equals_spec(spec_text: str) -> None:
    match = re.search(r"s_\{yr\}\s*=\s*([\d\\, ]+?)\$", spec_text)
    assert match is not None, "s_yr not found in the MRV specification"
    spec_value = int(re.sub(r"[^\d]", "", match.group(1)))
    assert spec_value == 31_536_000
    assert spec_value == SECONDS_PER_YEAR


def test_co2_agwp_coefficients_equal_spec(spec_text: str) -> None:
    rows = re.findall(
        r"^\|\s*(\d+)\s*\|\s*\$([\d.]+)\s*\\cdot\s*10\^\{(-?\d+)\}\$\s*\|",
        spec_text,
        flags=re.MULTILINE,
    )
    spec = {int(h): float(f"{m}e{e}") for h, m, e in rows}
    assert spec == {20: 24.16e-15, 50: 47.57e-15, 100: 74.36e-15}
    assert dict(CO2_AGWP_COEFF_WM2YR_PER_KG) == spec


def test_gwp_defaults_use_physics_constants() -> None:
    params = GWPParams()
    assert params.seconds_per_year == SECONDS_PER_YEAR
    assert dict(params.agwp_coeff_wm2yr_per_kg) == dict(CO2_AGWP_COEFF_WM2YR_PER_KG)
