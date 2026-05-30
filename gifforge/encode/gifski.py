# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""High-quality GIF encoding via gifski (https://gif.ski/).

Ported from ``gifski-post-processor.vala``. gifski consumes PNG frames, so it
is paired with :func:`ffmpeg.extract_frames`.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Optional, Sequence

from ..models import OutputFormat
from ..utils import check_for_executable, create_temp_file
from .runner import run_command

GIFSKI = "gifski"


def is_available() -> bool:
    return check_for_executable(GIFSKI)


def build_gifski_argv(
    frames: Sequence[Path], fps: int, quality: int, output_path: Path
) -> List[str]:
    argv = [
        GIFSKI,
        "--fps", str(fps),
        "--quality", str(quality),
        "-o", str(output_path),
    ]
    argv += [str(f) for f in frames]
    return argv


def encode_gif(
    frames: Sequence[Path],
    fps: int,
    quality: int,
    *,
    cancel_event: Optional[threading.Event] = None,
) -> Path:
    output = create_temp_file(OutputFormat.GIF.file_extension)
    run_command(
        build_gifski_argv(frames, fps, quality, output), cancel_event=cancel_event
    )
    return output
