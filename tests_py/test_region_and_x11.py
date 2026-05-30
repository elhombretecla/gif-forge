# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for region clipping/scaling and the x11grab command builder."""

from pathlib import Path

from gifforge.capture import region
from gifforge.capture.x11 import build_x11grab_argv
from gifforge.models import OutputFormat, RecordingArea, RecordingConfig


def test_clip_within_screen():
    area = region.prepare_area(
        100, 200, 300, 150, screen_width=1920, screen_height=1080
    )
    assert (area.left, area.top, area.width, area.height) == (100, 200, 300, 150)


def test_clip_overflow_right_and_bottom():
    area = region.prepare_area(
        1800, 1000, 400, 400, screen_width=1920, screen_height=1080
    )
    assert area.width == 120  # 1920 - 1800
    assert area.height == 80  # 1080 - 1000


def test_hidpi_scaling():
    area = region.prepare_area(
        10, 20, 100, 50, screen_width=1920, screen_height=1080, scale_factor=2
    )
    assert (area.left, area.top, area.width, area.height) == (20, 40, 200, 100)


def test_x11grab_argv_gif_path():
    cfg = RecordingConfig(output_format=OutputFormat.GIF, framerate=10, downsample=2)
    area = RecordingArea(100, 200, 640, 480)
    argv = build_x11grab_argv(area, cfg, Path("/tmp/out.webm"), ":0")
    assert "x11grab" in argv
    assert argv[argv.index("-video_size") + 1] == "640x480"
    assert argv[argv.index("-i") + 1] == ":0+100,200"
    assert argv[argv.index("-filter:v") + 1] == "scale=iw/2:-1"
    # GIF path uses a lossless VP9 intermediate.
    assert "-lossless" in argv
    assert argv[-2:] == ["-y", "/tmp/out.webm"]


def test_x11grab_framerate_floor_is_6():
    cfg = RecordingConfig(framerate=3)
    area = RecordingArea(0, 0, 100, 100)
    argv = build_x11grab_argv(area, cfg, Path("/tmp/o.webm"), ":0")
    assert argv[argv.index("-framerate") + 1] == "6"


def test_x11grab_no_mouse_adds_draw_mouse_zero():
    cfg = RecordingConfig(capture_mouse=False)
    area = RecordingArea(0, 0, 100, 100)
    argv = build_x11grab_argv(area, cfg, Path("/tmp/o.webm"), ":0")
    assert argv[argv.index("-draw_mouse") + 1] == "0"
