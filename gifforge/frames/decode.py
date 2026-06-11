# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Decode a recording (or loaded video) into PNG frames on disk.

Uses ffmpeg's image2 muxer to write one PNG per decoded frame into the session
cache, then builds a :class:`FrameList`. Frames inherit a uniform delay derived
from *fps* — correct for our constant-rate lossless intermediates. Reading true
per-frame delays from a variable-rate source (e.g. an imported GIF) is a later
enhancement.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from ..encode.ffmpeg import FFMPEG_BASE
from ..encode.runner import run_command
from ..project.cache import SessionCache
from .deglitch import find_capture_glitches
from .model import Frame, FrameList

log = logging.getLogger(__name__)


def decode_to_frames(
    input_path: Path,
    fps: int,
    cache: SessionCache,
    *,
    cancel_event: threading.Event | None = None,
) -> FrameList:
    """Extract every frame of *input_path* into *cache* and return a FrameList."""
    if fps <= 0:
        raise ValueError("fps must be positive")

    pattern = cache.frame_output_pattern
    argv = [*FFMPEG_BASE, "-i", str(input_path), str(pattern)]
    log.debug("decoding frames: %s", " ".join(argv))
    run_command(argv, cancel_event=cancel_event)

    files = cache.list_frames()
    if not files:
        raise RuntimeError("no frames were decoded from the recording")

    # Repair capture glitches (see frames/deglitch.py) by pointing each glitch
    # frame at its predecessor's PNG — frames sharing a path is the same
    # convention duplicated frames use, so the editor handles it natively.
    for i in find_capture_glitches(
        input_path, expected_frames=len(files), cancel_event=cancel_event
    ):
        files[i] = files[i - 1] if i > 0 else files[i + 1]

    delay_ms = round(1000 / fps)
    frames = FrameList(
        Frame(path=path, delay_ms=delay_ms, source_index=i)
        for i, path in enumerate(files)
    )
    log.info("decoded %d frames (%d ms each)", len(frames), delay_ms)
    return frames
