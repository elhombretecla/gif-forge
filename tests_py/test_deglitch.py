# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for capture glitch detection (pure detector + real ffmpeg decode).

The synthetic thumbnails mimic the real failure: x11grab under GNOME
Shell/NVIDIA occasionally returns one frame of bare wallpaper (or a partial
composite) that reverts on the very next frame.
"""

import shutil
import subprocess

import pytest

from gifforge.frames.deglitch import (
    THUMB_HEIGHT,
    THUMB_WIDTH,
    find_glitch_indices,
)

_SIZE = THUMB_WIDTH * THUMB_HEIGHT


def _solid(value: int) -> bytes:
    return bytes([value]) * _SIZE


def _banded(value: int, base: int = 0, fraction: float = 0.1) -> bytes:
    """A frame that differs from ``_solid(base)`` only in a top band."""
    band = int(_SIZE * fraction)
    return bytes([value]) * band + bytes([base]) * (_SIZE - band)


def test_no_glitch_in_static_clip():
    thumbs = [_solid(0)] * 10
    assert find_glitch_indices(thumbs) == []


def test_single_full_frame_glitch():
    thumbs = [_solid(0)] * 10
    thumbs[4] = _solid(200)  # wallpaper flash
    assert find_glitch_indices(thumbs) == [4]


def test_partial_band_glitch():
    # Mixed composite: only ~10% of the frame shows wallpaper.
    thumbs = [_solid(0)] * 10
    thumbs[6] = _banded(120)
    assert find_glitch_indices(thumbs) == [6]


def test_glitch_at_edges():
    thumbs = [_solid(0)] * 10
    thumbs[0] = _solid(200)
    thumbs[9] = _solid(200)
    assert find_glitch_indices(thumbs) == [0, 9]


def test_motion_is_not_a_glitch():
    # Steadily brightening content: each frame differs from both neighbours,
    # but the neighbours differ from each other even more.
    thumbs = [_solid(i * 20) for i in range(10)]
    assert find_glitch_indices(thumbs) == []


def test_oscillating_content_is_kept():
    # A spinner aliasing with the capture rate flags adjacent frames — that is
    # real animation, not a capture race, and must survive.
    thumbs = [_solid(0) if i % 2 == 0 else _solid(100) for i in range(10)]
    assert find_glitch_indices(thumbs) == []


def test_two_isolated_glitches():
    thumbs = [_solid(0)] * 12
    thumbs[3] = _solid(180)
    thumbs[8] = _banded(220, fraction=0.4)
    assert find_glitch_indices(thumbs) == [3, 8]


def test_short_clips_are_left_alone():
    assert find_glitch_indices([_solid(0), _solid(200)]) == []
    assert find_glitch_indices([]) == []


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_real_decode_repairs_glitch_frame(tmp_path, monkeypatch):
    """End to end: a webm with one foreign frame decodes with it repaired."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    import importlib
    from gifforge import utils as utils_mod
    importlib.reload(utils_mod)
    from gifforge.project import cache as cache_mod
    importlib.reload(cache_mod)
    from gifforge.frames import decode as decode_mod
    importlib.reload(decode_mod)

    # Build the clip from raw grayscale frames: black, with frame 5 white.
    width, height, count = 64, 36, 10
    frames = [bytes([0]) * (width * height) for _ in range(count)]
    frames[5] = bytes([255]) * (width * height)
    raw = tmp_path / "frames.raw"
    raw.write_bytes(b"".join(frames))

    sample = tmp_path / "sample.webm"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
         "-s", f"{width}x{height}", "-r", "10", "-i", str(raw),
         "-codec:v", "libvpx-vp9", "-lossless", "1", str(sample)],
        check=True, capture_output=True,
    )

    cache = cache_mod.SessionCache()
    try:
        decoded = decode_mod.decode_to_frames(sample, 10, cache)
        assert len(decoded) == count
        # The glitch frame now shares its predecessor's PNG.
        assert decoded[5].path == decoded[4].path
        # Its neighbours still point at their own files.
        assert decoded[4].path != decoded[6].path
    finally:
        cache.cleanup()
