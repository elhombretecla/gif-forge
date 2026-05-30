# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Encode an edited FrameList to GIF/WebM/APNG, honoring per-frame delays.

The editor produces frames with *variable* per-frame durations (from speed/delay
edits, dedup folding, etc.). The constant-fps ``encode_recording`` path can't
represent that, so exports go through ffmpeg's concat demuxer: each PNG is listed
with its own ``duration``, which becomes the frame's presentation timing. GIF and
APNG store per-frame delays natively, so the timing survives end to end.

``write_concat_file`` and the ``build_*_argv`` helpers are pure for unit testing;
``export_frames`` executes them.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Optional

from ..models import OutputFormat
from ..utils import create_temp_file
from .errors import EncodeError
from .ffmpeg import FFMPEG
from .runner import run_command


def _escape(path: Path) -> str:
    # Single-quote for the concat demuxer; escape embedded single quotes.
    return str(path).replace("'", "'\\''")


def write_concat_file(frames, concat_path: Path) -> Path:
    """Write an ffmpeg concat list with per-frame durations (seconds).

    The concat demuxer ignores the *last* entry's duration. Rather than the
    common repeat-last-frame hack (which leaves a spurious trailing frame), GIF
    export sets the final frame's delay explicitly via the muxer's
    ``-final_delay`` (see :func:`build_paletteuse_argv`).
    """
    frame_list = list(frames)
    if not frame_list:
        raise EncodeError("cannot export an empty timeline")
    lines: List[str] = []
    for frame in frame_list:
        lines.append(f"file '{_escape(Path(frame.path))}'")
        lines.append(f"duration {frame.delay_ms / 1000:.6f}")
    concat_path.write_text("\n".join(lines) + "\n")
    return concat_path


def final_delay_centiseconds(frames) -> int:
    """Last frame's delay in centiseconds (GIF delay unit), min 1."""
    frame_list = list(frames)
    last_ms = frame_list[-1].delay_ms if frame_list else 100
    return max(1, round(last_ms / 10))


def _concat_input(concat_path: Path) -> List[str]:
    return ["-f", "concat", "-safe", "0", "-i", str(concat_path)]


def build_palettegen_argv(concat_path: Path, palette_path: Path) -> List[str]:
    return [FFMPEG, "-y", *_concat_input(concat_path), "-vf", "palettegen", str(palette_path)]


def build_paletteuse_argv(
    concat_path: Path, palette_path: Path, output_path: Path,
    *, loop: bool, final_delay_cs: int,
) -> List[str]:
    return [
        FFMPEG, "-y",
        *_concat_input(concat_path),
        "-i", str(palette_path),
        "-lavfi", "paletteuse",
        "-loop", "0" if loop else "-1",
        "-final_delay", str(final_delay_cs),
        str(output_path),
    ]


def build_apng_argv(concat_path: Path, output_path: Path, *, loop: bool) -> List[str]:
    return [
        FFMPEG, "-y",
        *_concat_input(concat_path),
        "-f", "apng",
        "-plays", "0" if loop else "1",
        str(output_path),
    ]


def build_webm_argv(concat_path: Path, output_path: Path) -> List[str]:
    return [
        FFMPEG, "-y",
        *_concat_input(concat_path),
        "-codec:v", "libvpx-vp9",
        "-qmin", "10", "-qmax", "50", "-crf", "13",
        "-b:v", "1M", "-pix_fmt", "yuv420p",
        str(output_path),
    ]


def export_frames(
    frames,
    output_format: OutputFormat,
    output_path: Path,
    *,
    loop: bool = True,
    cancel_event: Optional[threading.Event] = None,
) -> Path:
    """Encode *frames* to *output_path* in *output_format*, honoring delays."""
    concat = create_temp_file("txt")
    try:
        write_concat_file(frames, concat)
        if output_format == OutputFormat.WEBM:
            run_command(build_webm_argv(concat, output_path), cancel_event=cancel_event)
        elif output_format == OutputFormat.APNG:
            run_command(
                build_apng_argv(concat, output_path, loop=loop),
                cancel_event=cancel_event,
            )
        else:  # GIF: 2-pass palette for quality
            palette = create_temp_file("png")
            try:
                run_command(
                    build_palettegen_argv(concat, palette), cancel_event=cancel_event
                )
                run_command(
                    build_paletteuse_argv(
                        concat, palette, output_path,
                        loop=loop, final_delay_cs=final_delay_centiseconds(frames),
                    ),
                    cancel_event=cancel_event,
                )
            finally:
                palette.unlink(missing_ok=True)
        return output_path
    finally:
        concat.unlink(missing_ok=True)
