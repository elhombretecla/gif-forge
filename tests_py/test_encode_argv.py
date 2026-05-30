# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests asserting the exact ffmpeg/gifski command lines.

These lock in the flags ported from Peek so we don't regress output quality.
"""

from pathlib import Path

from gifforge.encode import ffmpeg, gifski
from gifforge.models import OutputFormat


def test_palette_argv():
    argv = ffmpeg.build_palette_argv(Path("/in.webm"), 10, Path("/pal.png"))
    assert argv == [
        "ffmpeg", "-y",
        "-i", "/in.webm",
        "-vf", "fps=10,palettegen",
        "/pal.png",
    ]


def test_animation_argv_gif():
    argv = ffmpeg.build_animation_argv(
        Path("/in.webm"), Path("/pal.png"), 10, Path("/out.gif")
    )
    assert argv == [
        "ffmpeg", "-y",
        "-i", "/in.webm",
        "-i", "/pal.png",
        "-filter_complex", "fps=10,paletteuse",
        "/out.gif",
    ]


def test_animation_argv_apng_adds_plays():
    argv = ffmpeg.build_animation_argv(
        Path("/in.webm"), Path("/pal.png"), 15, Path("/out.apng"),
        output_format=OutputFormat.APNG,
    )
    assert "-plays" in argv and argv[argv.index("-plays") + 1] == "0"
    assert argv[-1] == "/out.apng"


def test_webm_argv():
    argv = ffmpeg.build_webm_argv(Path("/in.webm"), 24, Path("/out.webm"))
    assert argv[:3] == ["ffmpeg", "-y", "-i"]
    assert "libvpx-vp9" in argv
    assert argv[argv.index("-crf") + 1] == "13"
    assert argv[argv.index("-r") + 1] == "24"


def test_gifski_argv_appends_frames():
    frames = [Path("/f.0001.png"), Path("/f.0002.png")]
    argv = gifski.build_gifski_argv(frames, 12, 80, Path("/out.gif"))
    assert argv[:7] == [
        "gifski", "--fps", "12", "--quality", "80", "-o", "/out.gif",
    ]
    assert argv[7:] == ["/f.0001.png", "/f.0002.png"]
