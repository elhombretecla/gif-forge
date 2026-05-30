# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-frame image operations (crop).

Uses ffmpeg's ``crop`` filter so we stay dependency-light and consistent with
the rest of the pipeline. Cropped frames are written into the session cache;
the original PNGs are left untouched so undo can restore them.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Tuple

from ..encode.ffmpeg import FFMPEG
from ..encode.runner import run_command

log = logging.getLogger(__name__)

_crop_counter = 0


def crop_png(source: Path, rect: Tuple[int, int, int, int], cache) -> Path:
    """Crop *source* to ``(x, y, w, h)`` and return the new PNG path."""
    global _crop_counter
    x, y, w, h = rect
    if w <= 0 or h <= 0:
        raise ValueError("crop rectangle must have positive size")
    _crop_counter += 1
    out = cache.frames_dir / f"crop_{_crop_counter:05d}.png"
    argv = [
        FFMPEG, "-y", "-i", str(source),
        "-vf", f"crop={w}:{h}:{x}:{y}",
        str(out),
    ]
    run_command(argv)
    return out
