# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""FFmpeg-based encoding (GIF 2-pass, APNG, WebM).

The GIF path keeps Peek's 2-pass palette structure but tunes it for screen
captures: ``palettegen=stats_mode=diff`` weights the palette towards pixels
that actually change, and ``paletteuse=dither=bayer:diff_mode=rectangle`` only
re-encodes the changing rectangle per frame, which shrinks screencast GIFs
substantially. APNG is true-colour, so it is encoded directly (no palette).

The ``build_*_argv`` helpers are pure (no subprocess) for unit testing; the
``*_to`` functions execute them.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Sequence

from ..models import OutputFormat
from ..utils import create_temp_file
from .runner import run_command

FFMPEG = "ffmpeg"

# Shared prefix: quiet output (stderr stays small even on long runs) and no
# stdin probing, so ffmpeg can never stall waiting on either stream.
FFMPEG_BASE: List[str] = [FFMPEG, "-hide_banner", "-nostdin", "-y"]

PALETTEGEN = "palettegen=stats_mode=diff"
PALETTEUSE = "paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"


# --- pure argv builders (unit-testable) --------------------------------------


def drop_frames_prefix(drop_frames: Sequence[int] | None) -> str:
    """Filter-chain prefix removing capture glitch frames (see frames/deglitch).

    ``select`` keeps the surviving frames' timestamps, so the ``fps`` filter
    that follows fills each hole by repeating the previous good frame — the
    glitch is replaced rather than shortening the clip.
    """
    if not drop_frames:
        return ""
    terms = "+".join(f"eq(n,{i})" for i in sorted(drop_frames))
    return f"select='not({terms})',"


def build_palette_argv(
    input_path: Path,
    fps: int,
    palette_path: Path,
    drop_frames: Sequence[int] | None = None,
) -> List[str]:
    """ffmpeg pass 1: generate an optimized palette for the GIF."""
    return [
        *FFMPEG_BASE,
        "-i", str(input_path),
        "-vf", f"{drop_frames_prefix(drop_frames)}fps={fps},{PALETTEGEN}",
        str(palette_path),
    ]


def build_animation_argv(
    input_path: Path,
    palette_path: Path,
    fps: int,
    output_path: Path,
    drop_frames: Sequence[int] | None = None,
) -> List[str]:
    """ffmpeg pass 2: apply the palette to produce the final GIF."""
    return [
        *FFMPEG_BASE,
        "-i", str(input_path),
        "-i", str(palette_path),
        "-filter_complex", f"{drop_frames_prefix(drop_frames)}fps={fps},{PALETTEUSE}",
        str(output_path),
    ]


def build_apng_argv(
    input_path: Path,
    fps: int,
    output_path: Path,
    drop_frames: Sequence[int] | None = None,
) -> List[str]:
    """Encode APNG directly: it is true-colour, so a 256-colour palette pass
    would only degrade it."""
    return [
        *FFMPEG_BASE,
        "-i", str(input_path),
        "-vf", f"{drop_frames_prefix(drop_frames)}fps={fps}",
        "-f", "apng",
        "-plays", "0",  # loop forever, matching Peek
        str(output_path),
    ]


def build_webm_argv(input_path: Path, fps: int, output_path: Path) -> List[str]:
    """Encode the captured video to VP9 WebM (ported from ffmpeg.vala)."""
    return [
        *FFMPEG_BASE,
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
    return [*FFMPEG_BASE, "-i", str(input_path), str(pattern)]


# --- executors ----------------------------------------------------------------


def encode_gif(
    input_path: Path,
    fps: int,
    *,
    drop_frames: Sequence[int] | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Two-pass GIF encode. Returns the output file path."""
    palette = create_temp_file("png")
    try:
        run_command(
            build_palette_argv(input_path, fps, palette, drop_frames),
            cancel_event=cancel_event,
        )
        output = create_temp_file(OutputFormat.GIF.file_extension)
        run_command(
            build_animation_argv(input_path, palette, fps, output, drop_frames),
            cancel_event=cancel_event,
        )
        return output
    finally:
        palette.unlink(missing_ok=True)


def encode_apng(
    input_path: Path,
    fps: int,
    *,
    drop_frames: Sequence[int] | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    output = create_temp_file(OutputFormat.APNG.file_extension)
    run_command(
        build_apng_argv(input_path, fps, output, drop_frames), cancel_event=cancel_event
    )
    return output


def encode_webm(
    input_path: Path, fps: int, *, cancel_event: threading.Event | None = None
) -> Path:
    output = create_temp_file(OutputFormat.WEBM.file_extension)
    run_command(build_webm_argv(input_path, fps, output), cancel_event=cancel_event)
    return output


def extract_frames(
    input_path: Path, *, cancel_event: threading.Event | None = None
) -> List[Path]:
    """Extract frames as ``<input>.NNNN.png`` and return them sorted."""
    pattern = input_path.with_name(input_path.name + ".%04d.png")
    run_command(build_extract_frames_argv(input_path, pattern), cancel_event=cancel_event)
    glob_pat = input_path.name + ".*.png"
    return sorted(input_path.parent.glob(glob_pat))
