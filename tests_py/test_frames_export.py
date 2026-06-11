# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for exporting an edited FrameList (variable per-frame delays)."""

import shutil
import subprocess

import pytest

from gifforge.encode import frames_export
from gifforge.frames.model import Frame, FrameList
from gifforge.models import OutputFormat


def test_concat_file_has_durations(tmp_path):
    frames = FrameList([
        Frame(tmp_path / "a.png", 100, 0),
        Frame(tmp_path / "b.png", 250, 1),
    ])
    concat = frames_export.write_concat_file(frames, tmp_path / "list.txt")
    text = concat.read_text()
    assert "duration 0.100000" in text
    assert "duration 0.250000" in text


def test_final_delay_centiseconds():
    frames = FrameList([Frame("a", 100, 0), Frame("b", 250, 1)])
    assert frames_export.final_delay_centiseconds(frames) == 25


def test_gif_argv_loop_and_final_delay(tmp_path):
    loop = frames_export.build_paletteuse_argv(
        tmp_path / "l.txt", tmp_path / "p.png", tmp_path / "o.gif",
        loop=True, final_delay_cs=20,
    )
    once = frames_export.build_paletteuse_argv(
        tmp_path / "l.txt", tmp_path / "p.png", tmp_path / "o.gif",
        loop=False, final_delay_cs=5,
    )
    assert loop[loop.index("-loop") + 1] == "0"
    assert once[once.index("-loop") + 1] == "-1"
    assert loop[loop.index("-final_delay") + 1] == "20"


def test_apng_plays_flag(tmp_path):
    argv = frames_export.build_apng_argv(tmp_path / "l.txt", tmp_path / "o.apng", loop=True)
    assert argv[argv.index("-plays") + 1] == "0"
    assert "apng" in argv


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_real_export_reflects_edits(tmp_path):
    # Build 4 distinct frames, then export only 3 of them at custom delays.
    colors = ["red", "green", "blue", "yellow"]
    paths = []
    for i, color in enumerate(colors):
        p = tmp_path / f"f{i}.png"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        f"color=c={color}:s=64x48:d=1", "-frames:v", "1", str(p)],
                       check=True, capture_output=True)
        paths.append(p)

    # Edited timeline: drop frame 2, custom delays summing to 700ms.
    frames = FrameList([
        Frame(paths[0], 200, 0),
        Frame(paths[1], 300, 1),
        Frame(paths[3], 200, 3),
    ])

    out_gif = tmp_path / "out.gif"
    frames_export.export_frames(frames, OutputFormat.GIF, out_gif, loop=True)
    assert out_gif.exists()

    # Frame count reflects the edit (3 frames).
    n = subprocess.run(
        ["ffprobe", "-v", "error", "-count_packets",
         "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(out_gif)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert n == "3"

    # Duration reflects the custom delays (~0.7s).
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out_gif)],
        check=True, capture_output=True, text=True,
    ).stdout.strip())
    assert 0.6 <= dur <= 0.8

    # WebM and APNG also produce valid files.
    out_webm = tmp_path / "out.webm"
    frames_export.export_frames(frames, OutputFormat.WEBM, out_webm)
    assert out_webm.stat().st_size > 0

    out_apng = tmp_path / "out.apng"
    frames_export.export_frames(frames, OutputFormat.APNG, out_apng, loop=True)
    assert out_apng.stat().st_size > 0
