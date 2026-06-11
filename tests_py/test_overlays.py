# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the overlay model, Cairo rendering, and export with overlays."""

import shutil
import subprocess

import pytest

from gifforge.editor.overlays import (
    MouseClickOverlay,
    TextOverlay,
    overlay_from_dict,
)
from gifforge.frames.model import Frame, FrameList


def test_text_overlay_roundtrip():
    o = TextOverlay(start=2, end=5, text="hi", x=10, y=20, font_size=18)
    d = o.to_dict()
    assert d["kind"] == "text"
    back = overlay_from_dict(d)
    assert isinstance(back, TextOverlay)
    assert back.text == "hi" and back.start == 2 and back.end == 5


def test_click_overlay_roundtrip_and_applies():
    o = MouseClickOverlay(events=[(3, 40, 50)], radius=12, trail=2)
    back = overlay_from_dict(o.to_dict())
    assert isinstance(back, MouseClickOverlay)
    assert back.events == [(3, 40, 50)]  # tuples restored from JSON lists
    assert back.applies_to(3, 10) and back.applies_to(5, 10)
    assert not back.applies_to(6, 10) and not back.applies_to(2, 10)


def test_overlay_from_dict_rejects_bad_input():
    with pytest.raises(ValueError):
        overlay_from_dict({"kind": "nope"})
    with pytest.raises(ValueError):
        overlay_from_dict({"kind": "text", "evil_field": 1})
    with pytest.raises(ValueError):
        overlay_from_dict("not-a-dict")


def test_overlay_color_normalized_to_tuple():
    # JSON loads tuples back as lists; from_dict must restore tuples.
    o = TextOverlay(text="x", color=(1.0, 0.5, 0.0, 1.0))
    d = o.to_dict()
    d["color"] = list(d["color"])
    back = overlay_from_dict(d)
    assert back.color == (1.0, 0.5, 0.0, 1.0)


def test_text_applies_to_range():
    o = TextOverlay(start=1, end=3, text="x")
    assert [o.applies_to(i, 5) for i in range(5)] == [False, True, True, True, False]
    full = TextOverlay(start=0, end=-1, text="x")
    assert all(full.applies_to(i, 5) for i in range(5))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_render_overlays_changes_pixels(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    from gifforge import utils as utils_mod
    importlib.reload(utils_mod)
    from gifforge.project import cache as cache_mod
    importlib.reload(cache_mod)
    from gifforge.frames import overlay_render
    import cairo

    # A black 80x60 frame.
    src = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=80x60:d=1", "-frames:v", "1", str(src)],
                   check=True, capture_output=True)
    frames = FrameList([Frame(src, 100, 0), Frame(src, 100, 1)])

    overlays = [
        TextOverlay(start=0, end=-1, text="Hello", x=4, y=30, color=(1, 1, 1, 1)),
        MouseClickOverlay(events=[(0, 40, 30)], radius=10, color=(1, 0, 0, 1), trail=1),
    ]
    cache = cache_mod.SessionCache()
    out = overlay_render.render_overlays(frames, overlays, cache)
    assert len(out) == 2
    assert all(f.path.exists() for f in out)

    # Frame 0 has the red click marker at (40,30): that pixel should be reddish.
    surface = cairo.ImageSurface.create_from_png(str(out[0].path))
    data = bytes(surface.get_data())
    stride = surface.get_stride()
    # Cairo ARGB32 is premultiplied BGRA in memory.
    off = 30 * stride + 40 * 4
    b, g, r, _a = data[off], data[off + 1], data[off + 2], data[off + 3]
    assert r > 150 and g < 80 and b < 80  # red dot present
    cache.cleanup()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_export_with_overlays(tmp_path):
    from gifforge.frames.overlay_render import render_overlays
    from gifforge.encode.frames_export import export_frames
    from gifforge.models import OutputFormat
    from gifforge.project.cache import SessionCache

    src = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "color=c=blue:s=64x48:d=1", "-frames:v", "1", str(src)],
                   check=True, capture_output=True)
    frames = FrameList([Frame(src, 150, 0), Frame(src, 150, 1)])
    overlays = [TextOverlay(text="Demo", x=4, y=24)]

    cache = SessionCache()
    rendered = render_overlays(frames, overlays, cache)
    out = tmp_path / "out.gif"
    export_frames(rendered, OutputFormat.GIF, out, loop=True)
    assert out.exists() and out.stat().st_size > 0
    cache.cleanup()
