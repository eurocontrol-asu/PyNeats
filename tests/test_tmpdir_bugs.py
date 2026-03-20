"""Tests for the Small Emitter tmpdir fix.

Verifies that BaseStep subclasses correctly use `self.params` (instance-resolved)
instead of `self.default_params` (class type defaults) when accessing runtime
parameters like `tmp_base_dir_path`.

These tests are self-contained and do not require pycontrails, openairclim,
or pyBADA to be installed.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyneats.core.steps import BaseParams
from pyneats.core.steps import BaseStep


# ============================================================================
# Helpers: minimal step that mirrors OpenAirClim's pattern
# ============================================================================


@dataclass(frozen=True)
class _FakeClimateParams(BaseParams):
    """Mirrors OpenAirClimParams — a frozen dataclass with a default."""

    tmp_base_dir_path: str = ""
    grid_res: float = 5.0


class _FakeClimateModel(BaseStep):
    """Mirrors OpenAirClimModel — uses self.params (the fixed pattern)."""

    default_params = _FakeClimateParams

    def run(self, flight):
        return self.params.tmp_base_dir_path

    def get_grid_res(self):
        return self.params.grid_res


# ============================================================================
# Tests: self.params correctly resolves runtime parameters
# ============================================================================


class TestOpenAirClimParamsFix:
    """Verify that runtime params are correctly used via self.params.

    This validates the fix for the bug where OpenAirClimModel.run() used
    self.default_params (class type defaults) instead of self.params.
    """

    def test_params_are_correctly_stored_in_self_params(self):
        """BaseStep.__init__ stores resolved params in self.params."""
        model = _FakeClimateModel(tmp_base_dir_path="/tmp/writable")
        assert model.params.tmp_base_dir_path == "/tmp/writable"

    def test_runtime_tmp_path_is_used(self):
        """Runtime tmp_base_dir_path is correctly used via self.params."""
        model = _FakeClimateModel(tmp_base_dir_path="/tmp/writable")

        actual = model.run(None)

        assert actual == "/tmp/writable", (
            f"self.params.tmp_base_dir_path returns '{actual}' "
            f"instead of '/tmp/writable' (injected value)."
        )

    def test_runtime_grid_res_is_used(self):
        """Runtime grid_res is correctly used via self.params."""
        model = _FakeClimateModel(grid_res=99.0)

        actual = model.get_grid_res()

        assert actual == 99.0, (
            f"self.params.grid_res returns {actual} instead of 99.0 (injected value)."
        )

    def test_injected_tmp_path_overrides_default(self):
        """Injected tmp_base_dir_path is used instead of '' default.

        Previously, self.default_params always returned '' (the class default),
        causing tempfile.TemporaryDirectory(dir='') to create a relative tmp dir
        in the CWD, which is read-only on Azure Functions.
        """
        model = _FakeClimateModel(tmp_base_dir_path="/tmp/safe")
        dir_value = model.run(None)

        assert dir_value == "/tmp/safe", (
            f"Expected '/tmp/safe' (injected value) but got '{dir_value}'. "
            "self.params should return the injected value, not the class default."
        )

    def test_default_params_used_when_no_override(self):
        """When no params are passed, defaults are used correctly."""
        model = _FakeClimateModel()

        assert model.run(None) == ""
        assert model.get_grid_res() == 5.0
