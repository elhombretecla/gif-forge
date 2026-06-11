# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Detect single-frame capture glitches in a recording.

``x11grab`` reads the root window while the compositor repaints, so under a
compositing WM (observed on GNOME Shell + NVIDIA) an occasional frame catches
the screen mid-composite: the bare wallpaper — or a partial mix of wallpaper
and real content — flashes for exactly one captured frame and the next frame
is back to normal. Those frames are real pixels in the intermediate video, so
every encoder (ffmpeg and gifski alike) faithfully reproduces the flash.

The signature is unmistakable: frame *i* differs from BOTH neighbours while
the neighbours agree with each other. Detection runs on tiny grayscale
thumbnails extracted with a single extra ffmpeg pass, keeping this module
dependency-free (no PIL/numpy) and cheap even for long recordings.

Two guards keep false positives out:

* legitimately animating content (scrolling, video) makes the neighbours
  disagree with each other too, failing the agreement test;
* content that genuinely oscillates frame-by-frame (a spinner aliasing with
  the capture rate) flags *adjacent* frames, which are discarded — capture
  races are rare, isolated events, never back-to-back.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import List, Sequence

from ..encode.ffmpeg import FFMPEG_BASE
from ..encode.runner import run_command
from ..utils import create_temp_file

log = logging.getLogger(__name__)

# Thumbnail geometry: small enough that pure-Python pixel loops stay cheap,
# large enough that a partial (one-band) glitch still moves the mean.
THUMB_WIDTH = 64
THUMB_HEIGHT = 36
_THUMB_BYTES = THUMB_WIDTH * THUMB_HEIGHT

# Mean absolute difference (0..255) below which two thumbnails are "the same
# frame". The lossless VP9 intermediate has no noise, so static content sits
# at exactly 0; even the faintest observed partial glitch scored ~1.9.
_MIN_GLITCH_MAD = 1.0

# A glitch's neighbours must agree with each other at least this much more
# strongly than they agree with the glitch frame.
_NEIGHBOR_AGREEMENT = 0.25


def extract_thumbnails(
    video: Path, *, cancel_event: threading.Event | None = None
) -> List[bytes]:
    """Decode *video* into per-frame grayscale thumbnails (one ffmpeg pass)."""
    raw_path = create_temp_file("raw")
    try:
        run_command(
            [
                *FFMPEG_BASE,
                "-i", str(video),
                "-vf", f"scale={THUMB_WIDTH}:{THUMB_HEIGHT}",
                "-pix_fmt", "gray",
                "-f", "rawvideo",
                str(raw_path),
            ],
            cancel_event=cancel_event,
        )
        data = raw_path.read_bytes()
    finally:
        raw_path.unlink(missing_ok=True)
    count = len(data) // _THUMB_BYTES
    return [data[i * _THUMB_BYTES : (i + 1) * _THUMB_BYTES] for i in range(count)]


def _mad(a: bytes, b: bytes) -> float:
    """Mean absolute difference between two equal-size grayscale buffers."""
    total = 0
    for x, y in zip(a, b, strict=True):
        total += x - y if x >= y else y - x
    return total / len(a)


def _is_outlier(candidate: bytes, before: bytes, after: bytes) -> bool:
    """True if *candidate* differs from both sides while the sides agree."""
    d_before = _mad(candidate, before)
    if d_before < _MIN_GLITCH_MAD:
        return False
    d_after = _mad(candidate, after)
    if d_after < _MIN_GLITCH_MAD:
        return False
    d_sides = _mad(before, after)
    return d_sides <= _NEIGHBOR_AGREEMENT * min(d_before, d_after)


def find_glitch_indices(thumbs: Sequence[bytes]) -> List[int]:
    """Indices of single-frame glitches in *thumbs* (pure, unit-testable)."""
    n = len(thumbs)
    if n < 3:
        return []
    flagged = [
        i for i in range(1, n - 1) if _is_outlier(thumbs[i], thumbs[i - 1], thumbs[i + 1])
    ]
    # Edge frames have one neighbour only; test them against the next two.
    if 0 not in flagged and 1 not in flagged:
        if _is_outlier(thumbs[0], thumbs[1], thumbs[2]):
            flagged.insert(0, 0)
    if (n - 1) not in flagged and (n - 2) not in flagged:
        if _is_outlier(thumbs[n - 1], thumbs[n - 2], thumbs[n - 3]):
            flagged.append(n - 1)
    # Adjacent flags mean oscillating *content* (see module docstring) — keep it.
    return [
        i for i in flagged if (i - 1) not in flagged and (i + 1) not in flagged
    ]


def find_capture_glitches(
    video: Path,
    *,
    expected_frames: int | None = None,
    cancel_event: threading.Event | None = None,
) -> List[int]:
    """Detect glitch frame indices in *video*.

    If *expected_frames* is given and the thumbnail pass disagrees on the
    frame count, detection is skipped (indices would not line up with the
    caller's frames) — better to keep a glitch than corrupt good frames.
    """
    try:
        thumbs = extract_thumbnails(video, cancel_event=cancel_event)
    except Exception as exc:  # noqa: BLE001 - detection must never break decode
        log.warning("glitch detection skipped (thumbnail pass failed): %s", exc)
        return []
    if expected_frames is not None and len(thumbs) != expected_frames:
        log.warning(
            "glitch detection skipped: thumbnail pass found %d frames, expected %d",
            len(thumbs), expected_frames,
        )
        return []
    glitches = find_glitch_indices(thumbs)
    if glitches:
        log.info(
            "found %d capture glitch frame(s) at indices %s", len(glitches), glitches
        )
    return glitches
