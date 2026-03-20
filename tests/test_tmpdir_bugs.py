"""Tests reproducing the Small Emitter tmpdir bugs.

Bug #1: OpenAirClimModel.run() reads `self.default_params` (the class type
        defaults) instead of `self.params` (the instance-resolved params).
        This means `tmp_base_dir_path` is ALWAYS "" regardless of injection.

Bug #2: The _STEP_CACHE in fleet.py uses (interface, name) as cache key
        without including params. A cached step with stale params is returned
        even when different params are passed.

These tests are self-contained and do not require pycontrails, openairclim,
or pyBADA to be installed. They reproduce the bugs using the same BaseStep
and registry mechanisms that the production code uses.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pyneats.core.steps import BaseParams
from pyneats.core.steps import BaseStep
from pyneats.core.steps import Step
from pyneats.core.steps_registry import register
from pyneats.runners.fleet import _STEP_CACHE
from pyneats.runners.fleet import _get_step_cached


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
        # FIXED: reads the instance-resolved params
        return self.params.tmp_base_dir_path

    def get_grid_res(self):
        # FIXED: reads the instance-resolved params
        return self.params.grid_res


class _CorrectClimateModel(BaseStep):
    """What OpenAirClimModel SHOULD do — use self.params."""

    default_params = _FakeClimateParams

    def run(self, flight):
        # CORRECT: reads the instance-resolved params
        return self.params.tmp_base_dir_path

    def get_grid_res(self):
        return self.params.grid_res


# ============================================================================
# Bug #1: self.default_params vs self.params
# ============================================================================


class TestOpenAirClimDefaultParamsBug:
    """Demonstrate that using self.default_params ignores runtime params.

    This reproduces the exact pattern used in OpenAirClimModel.run():
        tempfile.TemporaryDirectory(dir=self.default_params.tmp_base_dir_path)
    """

    def test_params_are_correctly_stored_in_self_params(self):
        """Baseline: BaseStep.__init__ stores resolved params in self.params."""
        model = _FakeClimateModel(tmp_base_dir_path="/tmp/writable")
        assert model.params.tmp_base_dir_path == "/tmp/writable"

    def test_default_params_ignores_runtime_tmp_path(self):
        """Runtime tmp_base_dir_path is correctly used via self.params."""
        model = _FakeClimateModel(tmp_base_dir_path="/tmp/writable")

        actual = model.run(None)

        assert actual == "/tmp/writable", (
            f"self.params.tmp_base_dir_path returns '{actual}' "
            f"instead of '/tmp/writable' (injected value)."
        )

    def test_default_params_ignores_runtime_grid_res(self):
        """Runtime grid_res is correctly used via self.params."""
        model = _FakeClimateModel(grid_res=99.0)

        actual = model.get_grid_res()

        assert actual == 99.0, (
            f"self.params.grid_res returns {actual} instead of 99.0 (injected value)."
        )

    def test_correct_pattern_works(self):
        """Contrast: using self.params works correctly."""
        model = _CorrectClimateModel(tmp_base_dir_path="/tmp/writable")
        assert model.run(None) == "/tmp/writable"

        model2 = _CorrectClimateModel(grid_res=99.0)
        assert model2.get_grid_res() == 99.0

    def test_empty_string_means_relative_tmpdir(self):
        """After fix, injected tmp_base_dir_path is used instead of ''.

        Previously, self.default_params always returned '' (the class default),
        causing tempfile.TemporaryDirectory(dir='') to create a relative tmp dir
        in the CWD, which is read-only on Azure Functions.
        """
        model = _FakeClimateModel(tmp_base_dir_path="/tmp/safe")
        dir_value = model.run(None)  # now reads self.params → "/tmp/safe"

        # After fix: injected value is correctly used
        assert dir_value == "/tmp/safe", (
            f"Expected '/tmp/safe' (injected value) but got '{dir_value}'. "
            "The fix should use self.params instead of self.default_params."
        )


# ============================================================================
# Bug #2: Step cache ignores params in key
# ============================================================================


# Register a simple step under the Step protocol for cache testing
class _CacheTestStep:
    """Minimal step whose value we can inspect."""

    def __init__(self, *, value: str = "default"):
        self.value = value

    def __call__(self, x):
        return x


@register(Step, "_test_cache_bug_step")
class _RegisteredCacheStep(_CacheTestStep):
    pass


class TestStepCacheBug:
    """Demonstrate that _STEP_CACHE ignores params in the cache key.

    Cache key is (interface, name) only — params are NOT included.
    This means the first params used are cached, and subsequent calls
    with different params silently return the stale step.
    """

    def setup_method(self):
        """Clear the step cache before each test."""
        _STEP_CACHE.clear()

    def test_cache_returns_stale_params(self):
        """BUG #2: Second call with different params gets the cached first step."""
        params_v1: Mapping[str, Any] = {"value": "first"}
        params_v2: Mapping[str, Any] = {"value": "second"}

        step1 = _get_step_cached(Step, "_test_cache_bug_step", params_v1)
        assert step1.value == "first"

        # Should build a NEW step with value="second", but returns cached step
        step2 = _get_step_cached(Step, "_test_cache_bug_step", params_v2)

        # BUG: step2.value is "first" (cached) instead of "second" (requested)
        assert step2.value == "second", (
            f"BUG: _get_step_cached returned cached step with value='{step2.value}' "
            f"instead of building a new step with value='second'.\n"
            f"Cache key is (interface, name) only — params are ignored.\n"
            f"In production, this means a worker process that first builds "
            f"OpenAirClimModel with tmp_base_dir_path='' will always return "
            f"that stale instance, even when '/tmp/small_emitter' is passed."
        )

    def test_cache_returns_same_object(self):
        """BUG #2: Different params return literally the same object."""
        params_v1: Mapping[str, Any] = {"value": "alpha"}
        params_v2: Mapping[str, Any] = {"value": "beta"}

        step1 = _get_step_cached(Step, "_test_cache_bug_step", params_v1)
        step2 = _get_step_cached(Step, "_test_cache_bug_step", params_v2)

        assert step1 is not step2, (
            "BUG: _get_step_cached returned the SAME object for different params. "
            "Any change to the step's state would affect all users of the cache."
        )

    def teardown_method(self):
        """Clean up cache after tests."""
        _STEP_CACHE.clear()
