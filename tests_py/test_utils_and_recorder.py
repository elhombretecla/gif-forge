# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for stale temp cleanup and the controller's WebM passthrough."""

import importlib
import os
import time
from pathlib import Path

import pytest


@pytest.fixture
def utils_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    from gifforge import utils as mod

    importlib.reload(mod)
    return mod


def test_cleanup_stale_temp_files(utils_mod):
    fresh = utils_mod.create_temp_file("webm")
    stale_file = utils_mod.create_temp_file("webm")
    stale_dir = utils_mod.create_temp_dir()
    old = time.time() - 10 * 24 * 3600
    os.utime(stale_file, (old, old))
    os.utime(stale_dir, (old, old))

    removed = utils_mod.cleanup_stale_temp_files()

    assert removed == 2
    assert fresh.exists()
    assert not stale_file.exists()
    assert not stale_dir.exists()


def test_cleanup_never_touches_autosaves(utils_mod):
    autosave_dir = utils_mod.cache_dir() / "autosave"
    autosave_dir.mkdir()
    snapshot = autosave_dir / "session.gifforge"
    snapshot.write_bytes(b"x")
    old = time.time() - 10 * 24 * 3600
    os.utime(autosave_dir, (old, old))
    os.utime(snapshot, (old, old))

    utils_mod.cleanup_stale_temp_files()

    assert snapshot.exists()


class _FakeFinalBackend:
    """Backend whose intermediate is already the final output (WebM on X11)."""

    name = "fake"

    def __init__(self, output: Path) -> None:
        self._output = output
        self.intermediate_is_final = True
        self.cancelled = False

    def start(self, area) -> None:  # pragma: no cover - not exercised
        pass

    def stop(self) -> Path:
        return self._output

    def cancel(self) -> None:
        self.cancelled = True


def test_controller_passes_final_intermediate_through(tmp_path, monkeypatch):
    from gifforge import recorder as recorder_mod
    from gifforge.models import RecordingArea, RecordingConfig

    output = tmp_path / "final.webm"
    output.write_bytes(b"webm-bytes")
    backend = _FakeFinalBackend(output)
    backend.start_called = False
    monkeypatch.setattr(
        recorder_mod, "create_backend", lambda config, prefer=None: backend
    )

    controller = recorder_mod.RecordingController(RecordingConfig())
    controller.start(RecordingArea(0, 0, 10, 10))
    result = controller.stop_and_encode()

    # No re-encode: the recorded file itself is returned, untouched.
    assert result == output
    assert output.read_bytes() == b"webm-bytes"
