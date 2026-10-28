"""The OpenAirClim temp folder is created, and an unusable one fails at start-up.

Every small-emitter flight opens a temporary folder inside ``tmp_base_dir_path``.
Nothing created that folder, so with a missing folder every flight failed at
the last step (``integrated_non_co2``), after parsing, performance and
emissions had run for the whole fleet.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


pytest.importorskip("openairclim", reason="openairclim required for Method D imports")

from pyneats.runners.small_emitter import FleetRunnerSmallEmitter
from pyneats.runners.small_emitter import FlightRunnerSmallEmitter
from pyneats.runners.small_emitter import SmallFleetRunnerParams
from pyneats.steps.climate_functions import open_airclim
from pyneats.steps.climate_functions.open_airclim import OpenAirClimModel
from pyneats.steps.climate_functions.open_airclim import prepare_tmp_base_dir
from pyneats.steps.weather.weather_store import ZarrPaths


needs_permissions = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root can write to read-only folders",
)


@pytest.fixture
def read_only_dir(tmp_path: Path):
    ro = tmp_path / "read_only"
    ro.mkdir()
    ro.chmod(0o500)
    yield ro
    ro.chmod(0o700)


def test_missing_nested_folder_is_created(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "oac"
    prepare_tmp_base_dir(str(target))
    assert target.is_dir()


def test_existing_folder_is_kept(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("x")
    prepare_tmp_base_dir(str(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["keep.txt"]


def test_empty_path_means_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    prepare_tmp_base_dir("")
    assert list(tmp_path.iterdir()) == []


@needs_permissions
def test_folder_in_read_only_parent_fails_with_path(read_only_dir: Path) -> None:
    target = read_only_dir / "oac"
    with pytest.raises(ValueError, match=str(target)):
        prepare_tmp_base_dir(str(target))


@needs_permissions
def test_read_only_folder_fails_with_path(read_only_dir: Path) -> None:
    with pytest.raises(ValueError, match=str(read_only_dir)):
        prepare_tmp_base_dir(str(read_only_dir))


def test_file_in_place_of_folder_fails_with_path(tmp_path: Path) -> None:
    target = tmp_path / "not_a_folder"
    target.write_text("x")
    with pytest.raises(ValueError, match=str(target)):
        prepare_tmp_base_dir(str(target))


def _fleet_params(tmp_base_dir_path: str) -> SmallFleetRunnerParams:
    return SmallFleetRunnerParams(
        trajectory_json_filepath="unused.json",
        zarr_paths=ZarrPaths(met_store="unused.zarr", rad_store="unused.zarr"),
        tmp_base_dir_path=tmp_base_dir_path,
    )


@needs_permissions
def test_fleet_runner_fails_at_start_up(read_only_dir: Path) -> None:
    target = read_only_dir / "oac"
    with pytest.raises(ValueError, match=str(target)):
        FleetRunnerSmallEmitter(_fleet_params(str(target)))


@needs_permissions
def test_flight_runner_fails_at_start_up(read_only_dir: Path) -> None:
    target = read_only_dir / "oac"
    with pytest.raises(ValueError, match=str(target)):
        FlightRunnerSmallEmitter(weather=None, tmp_base_dir_path=str(target))  # type: ignore[arg-type]


def test_model_creates_missing_folder_before_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct use of the model (no runner) also gets the folder created."""
    target = tmp_path / "x" / "oac"
    seen: list[bool] = []

    class _StopError(Exception):
        pass

    def _temporary_directory(dir: str):
        seen.append(Path(dir).is_dir())
        raise _StopError

    monkeypatch.setattr(
        open_airclim.tempfile, "TemporaryDirectory", _temporary_directory
    )
    model = OpenAirClimModel(tmp_base_dir_path=str(target))
    with pytest.raises(_StopError):
        model.run(None)  # type: ignore[arg-type]
    assert seen == [True]
