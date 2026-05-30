# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""FFmpeg-based encoding (GIF 2-pass, APNG, WebM).

Command-line flags are ported verbatim from Peek's
``ffmpeg-post-processor.vala`` and ``ffmpeg.vala`` so output matches Peek.

The ``build_*_argv`` helpers are pure (no subprocess) for unit testing; the
``*_to`` functions execute them.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Optional

from ..models import OutputFormat
from ..utils import create_temp_file
from .runner import run_command

FFMPEG = "ffmpeg"


# --- pure argv builders (unit-testable) --------------------------------------


def build_palette_argv(input_path: Path, fps: int, palette_path: Path) -> List[str]:
    """ffmpeg pass 1: generate an optimized palette for the GIF/APNG."""
    return [
        FFMPEG, "-y",
        "-i", str(input_path),
        "-vf", f"fps={fps},palettegen",
        str(palette_path),
    ]


def build_animation_argv(
    input_path: Path,
    palette_path: Path,
    fps: int,
    output_path: Path,
    *,
    output_format: OutputFormat = OutputFormat.GIF,
) -> List[str]:
    """ffmpeg pass 2: apply the palette to produce the final GIF/APNG."""
    argv = [
        FFMPEG, "-y",
        "-i", str(input_path),
        "-i", str(palette_path),
        "-filter_complex", f"fps={fps},paletteuse",
    ]
    if output_format == OutputFormat.APNG:
        # Loop forever, matching Peek.
        argv += ["-plays", "0"]
    argv.append(str(output_path))
    return argv


def build_webm_argv(input_path: Path, fps: int, output_path: Path) -> List[str]:
    """Encode the captured video to VP9 WebM (ported from ffmpeg.vala)."""
    return [
        FFMPEG, "-y",
        "-i", str(input_path),
        "-codec:v", "libvpx-vp9",
        "-qmin", "10",
        "-qmax", "50",
        "-crf", "13",
        "-b:v", "1M",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        str(output_path),
    ]


def build_extract_frames_argv(input_path: Path, pattern: Path) -> List[str]:
    """Extract PNG frames (pass before gifski). Ported from extract-frames."""
    return [FFMPEG, "-y", "-i", str(input_path), str(pattern)]


# --- executors ----------------------------------------------------------------


def encode_gif_or_apng(
    input_path: Path,
    fps: int,
    *,
    output_format: OutputFormat = OutputFormat.GIF,
    cancel_event: Optional[threading.Event] = None,
) -> Path:
    """Two-pass GIF/APNG encode. Returns the output file path."""
    palette = create_temp_file("png")
    try:
        run_command(
            build_palette_argv(input_path, fps, palette), cancel_event=cancel_event
        )
        output = create_temp_file(output_format.file_extension)
        run_command(
            build_animation_argv(
                input_path, palette, fps, output, output_format=output_format
            ),
            cancel_event=cancel_event,
        )
        return output
    finally:
        palette.unlink(missing_ok=True)


def encode_webm(
    input_path: Path, fps: int, *, cancel_event: Optional[threading.Event] = None
) -> Path:
    output = create_temp_file(OutputFormat.WEBM.file_extension)
    run_command(build_webm_argv(input_path, fps, output), cancel_event=cancel_event)
    return output


def extract_frames(
    input_path: Path, *, cancel_event: Optional[threading.Event] = None
) -> List[Path]:
    """Extract frames as ``<input>.NNNN.png`` and return them sorted."""
    pattern = input_path.with_name(input_path.name + ".%04d.png")
    run_command(build_extract_frames_argv(input_path, pattern), cancel_event=cancel_event)
    glob_pat = input_path.name + ".*.png"
    return sorted(input_path.parent.glob(glob_pat))
