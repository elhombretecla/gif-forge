# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the in-place GIF delay rewrite (gif_timing)."""

import struct

import pytest

from gifforge.encode.gif_timing import (
    delays_centiseconds,
    rewrite_gif_delays,
)
from gifforge.encode import gif_timing


def _minimal_gif(frame_delays_cs, with_gct=True) -> bytes:
    """Hand-build a tiny valid GIF89a with one GCE per 1x1 frame."""
    out = bytearray(b"GIF89a")
    gct_flag = 0x80 | 0x00 if with_gct else 0x00  # 2-entry table
    out += struct.pack("<HHBBB", 1, 1, gct_flag, 0, 0)  # LSD
    if with_gct:
        out += bytes(6)  # 2 RGB entries
    for delay in frame_delays_cs:
        out += bytes([0x21, 0xF9, 4, 0]) + struct.pack("<H", delay) + bytes([0, 0])
        out += bytes([0x2C]) + struct.pack("<HHHH", 0, 0, 1, 1) + bytes([0x00])
        out += bytes([2, 1, 0x4C, 0])  # LZW min code size + 1 data sub-block
    out += bytes([0x3B])
    return bytes(out)


def _read_delays(data: bytes):
    offsets = gif_timing._gce_delay_offsets(data)
    return [struct.unpack_from("<H", data, off)[0] for off in offsets]


def test_delays_centiseconds_exact():
    assert delays_centiseconds([100, 100, 100]) == [10, 10, 10]


def test_delays_centiseconds_cumulative_rounding():
    # 125 ms is not representable per-frame; the total must not drift.
    cs = delays_centiseconds([125] * 8)
    assert sum(cs) == 100  # 1000 ms exactly
    assert all(c in (12, 13) for c in cs)


def test_delays_centiseconds_minimum_one():
    assert delays_centiseconds([0, 0]) == [1, 1]


def test_rewrite_patches_each_frame(tmp_path):
    gif = tmp_path / "t.gif"
    gif.write_bytes(_minimal_gif([12, 8, 12]))
    assert rewrite_gif_delays(gif, [10, 10, 10]) is True
    assert _read_delays(gif.read_bytes()) == [10, 10, 10]


def test_rewrite_without_global_color_table(tmp_path):
    gif = tmp_path / "t.gif"
    gif.write_bytes(_minimal_gif([5, 5], with_gct=False))
    assert rewrite_gif_delays(gif, [25, 30]) is True
    assert _read_delays(gif.read_bytes()) == [25, 30]


def test_rewrite_skips_on_frame_count_mismatch(tmp_path):
    gif = tmp_path / "t.gif"
    original = _minimal_gif([12, 8])
    gif.write_bytes(original)
    assert rewrite_gif_delays(gif, [10, 10, 10]) is False
    assert gif.read_bytes() == original  # untouched


def test_rewrite_rejects_non_gif(tmp_path):
    bogus = tmp_path / "t.gif"
    bogus.write_bytes(b"not a gif at all")
    assert rewrite_gif_delays(bogus, [10]) is False


def test_rewrite_clamps_delay_range(tmp_path):
    gif = tmp_path / "t.gif"
    gif.write_bytes(_minimal_gif([10]))
    assert rewrite_gif_delays(gif, [0]) is True
    assert _read_delays(gif.read_bytes()) == [1]


@pytest.mark.skipif(
    __import__("shutil").which("ffmpeg") is None, reason="ffmpeg not installed"
)
def test_export_frames_produces_exact_delays(tmp_path):
    """The editor GIF export must not show the concat 120/80 ms jitter."""
    import subprocess
    from gifforge.encode import frames_export
    from gifforge.frames.model import Frame, FrameList
    from gifforge.models import OutputFormat

    paths = []
    for i, color in enumerate(["red", "green", "blue"]):
        p = tmp_path / f"f{i}.png"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                        f"color=c={color}:s=64x48:d=1", "-frames:v", "1", str(p)],
                       check=True, capture_output=True)
        paths.append(p)
    frames = FrameList([Frame(p, 100, i) for i, p in enumerate(paths)])

    out = tmp_path / "out.gif"
    frames_export.export_frames(frames, OutputFormat.GIF, out, loop=True)
    assert _read_delays(out.read_bytes()) == [10, 10, 10]
