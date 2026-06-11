# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests asserting the exact ffmpeg/gifski command lines.

These lock in the screencast-tuned flags so we don't regress output quality
(or reintroduce the stderr-deadlock / stdin-stall ffmpeg failure modes).
"""

from pathlib import Path

from gifforge.encode import ffmpeg, gifski
from gifforge.encode.ffmpeg import FFMPEG_BASE


def test_base_flags_keep_ffmpeg_quiet_and_stdin_free():
    # -nostdin prevents stdin stalls; -hide_banner keeps stderr small so the
    # un-read pipe can never fill up and block ffmpeg.
    assert FFMPEG_BASE == ["ffmpeg", "-hide_banner", "-nostdin", "-y"]


def test_palette_argv():
    argv = ffmpeg.build_palette_argv(Path("/in.webm"), 10, Path("/pal.png"))
    assert argv == [
        *FFMPEG_BASE,
        "-i", "/in.webm",
        "-vf", "fps=10,palettegen=stats_mode=diff",
        "/pal.png",
    ]


def test_animation_argv_gif():
    argv = ffmpeg.build_animation_argv(
        Path("/in.webm"), Path("/pal.png"), 10, Path("/out.gif")
    )
    assert argv == [
        *FFMPEG_BASE,
        "-i", "/in.webm",
        "-i", "/pal.png",
        "-filter_complex",
        "fps=10,paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
        "/out.gif",
    ]


def test_apng_is_direct_true_colour():
    # APNG is true-colour: it must NOT go through the 256-colour palette pass.
    argv = ffmpeg.build_apng_argv(Path("/in.webm"), 15, Path("/out.apng"))
    assert "palettegen" not in " ".join(argv)
    assert argv[argv.index("-f") + 1] == "apng"
    assert argv[argv.index("-plays") + 1] == "0"
    assert argv[-1] == "/out.apng"


def test_webm_argv():
    argv = ffmpeg.build_webm_argv(Path("/in.webm"), 24, Path("/out.webm"))
    assert argv[: len(FFMPEG_BASE)] == FFMPEG_BASE
    assert "libvpx-vp9" in argv
    assert argv[argv.index("-crf") + 1] == "13"
    assert argv[argv.index("-r") + 1] == "24"


def test_drop_frames_prefix_empty():
    assert ffmpeg.drop_frames_prefix(None) == ""
    assert ffmpeg.drop_frames_prefix([]) == ""


def test_drop_frames_prefix_selects_out_glitches():
    # The select must come BEFORE fps so the indices match the source frames
    # and fps refills each hole by repeating the previous good frame.
    argv = ffmpeg.build_palette_argv(Path("/in.webm"), 10, Path("/pal.png"), [7, 3])
    vf = argv[argv.index("-vf") + 1]
    assert vf == "select='not(eq(n,3)+eq(n,7))',fps=10,palettegen=stats_mode=diff"

    argv = ffmpeg.build_animation_argv(
        Path("/in.webm"), Path("/pal.png"), 10, Path("/out.gif"), [3]
    )
    fc = argv[argv.index("-filter_complex") + 1]
    assert fc.startswith("select='not(eq(n,3))',fps=10,paletteuse=")

    argv = ffmpeg.build_apng_argv(Path("/in.webm"), 15, Path("/out.apng"), [0])
    vf = argv[argv.index("-vf") + 1]
    assert vf == "select='not(eq(n,0))',fps=15"


def test_gifski_argv_appends_frames():
    frames = [Path("/f.0001.png"), Path("/f.0002.png")]
    argv = gifski.build_gifski_argv(frames, 12, 80, Path("/out.gif"))
    assert argv[:7] == [
        "gifski", "--fps", "12", "--quality", "80", "-o", "/out.gif",
    ]
    assert argv[7:] == ["/f.0001.png", "/f.0002.png"]


def test_gifski_argv_limit():
    few = [Path(f"/frames/{i:05d}.png") for i in range(100)]
    assert gifski.frames_within_argv_limit(few)
    # ~100k paths of ~20 bytes ≈ 2 MB > limit.
    many = [Path(f"/frames/{i:09d}.png") for i in range(100_000)]
    assert not gifski.frames_within_argv_limit(many)
