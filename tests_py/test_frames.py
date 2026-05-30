# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the frame model (pure) and real ffmpeg decode."""

import shutil
import subprocess
from pathlib import Path

import pytest

from gifforge.frames.model import Frame, FrameList


def _frames(n, delay=100):
    return FrameList(Frame(Path(f"/f{i}.png"), delay, i) for i in range(n))


def test_total_duration():
    assert _frames(5, 100).total_duration_ms == 500


def test_remove_and_insert():
    fl = _frames(3)
    removed = fl.remove_at(1)
    assert removed.source_index == 1
    assert [f.source_index for f in fl] == [0, 2]
    fl.insert(1, removed)
    assert [f.source_index for f in fl] == [0, 1, 2]


def test_remove_indices():
    fl = _frames(5)
    removed = fl.remove_indices([1, 3])
    assert [f.source_index for f in removed] == [1, 3]
    assert [f.source_index for f in fl] == [0, 2, 4]


def test_move():
    fl = _frames(4)
    fl.move(0, 2)
    assert [f.source_index for f in fl] == [1, 2, 0, 3]


def test_duplicate_shares_path():
    fl = _frames(2)
    dup = fl.duplicate(0)
    assert len(fl) == 3
    assert fl[0].path == fl[1].path == dup.path  # same PNG on disk
    assert [f.source_index for f in fl] == [0, 0, 1]


def test_trim():
    fl = _frames(6)
    fl.trim(2, 4)
    assert [f.source_index for f in fl] == [2, 3, 4]


def test_trim_invalid():
    with pytest.raises(IndexError):
        _frames(3).trim(2, 5)


def test_set_delay_and_reverse():
    fl = _frames(3)
    fl.set_delay(0, 250)
    assert fl[0].delay_ms == 250
    fl.set_delay(1, -10)
    assert fl[1].delay_ms == 0  # clamped
    fl.reverse()
    assert [f.source_index for f in fl] == [2, 1, 0]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_real_decode(tmp_path, monkeypatch):
    # Generate a 1s, 10fps clip -> expect 10 frames at 100ms each.
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    import importlib
    from gifforge import utils as utils_mod
    importlib.reload(utils_mod)
    from gifforge.project import cache as cache_mod
    importlib.reload(cache_mod)
    from gifforge.frames import decode as decode_mod
    importlib.reload(decode_mod)

    sample = tmp_path / "sample.webm"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "testsrc=duration=1:size=160x120:rate=10",
         "-codec:v", "libvpx-vp9", "-lossless", "1", str(sample)],
        check=True, capture_output=True,
    )

    cache = cache_mod.SessionCache()
    try:
        frames = decode_mod.decode_to_frames(sample, 10, cache)
        assert len(frames) == 10
        assert all(f.delay_ms == 100 for f in frames)
        assert frames.total_duration_ms == 1000
        assert all(f.path.exists() for f in frames)
    finally:
        cache.cleanup()
        assert not cache.root.exists()
