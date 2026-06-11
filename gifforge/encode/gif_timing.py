# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rewrite the per-frame delays of an encoded GIF in place.

ffmpeg's concat demuxer rounds each entry's ``duration`` to the PNG stream's
1/25s timebase, so the editor's 100 ms frames reach the GIF muxer as
alternating 120/80 ms — visibly jerky playback. Rather than fight the
demuxer (per-file ffconcat options need ffmpeg ≥ 7), the exact delays are
patched into the finished file: a GIF's frame delay is a little-endian uint16
of centiseconds inside each Graphic Control Extension, so this is a plain
binary rewrite with no re-encode and no quality impact.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Sequence

log = logging.getLogger(__name__)

_EXTENSION_INTRODUCER = 0x21
_GRAPHIC_CONTROL_LABEL = 0xF9
_IMAGE_SEPARATOR = 0x2C
_TRAILER = 0x3B


def delays_centiseconds(delays_ms: Sequence[int]) -> List[int]:
    """Convert millisecond delays to centiseconds with cumulative rounding.

    Rounding each delay independently would drift on values like 125 ms; by
    rounding the running total instead, the error stays under 5 ms overall.
    """
    out: List[int] = []
    total_ms = 0
    emitted_cs = 0
    for ms in delays_ms:
        total_ms += ms
        cs = max(1, round(total_ms / 10) - emitted_cs)
        emitted_cs += cs
        out.append(cs)
    return out


def _skip_sub_blocks(data: bytes | bytearray, pos: int) -> int:
    """Return the offset just past a sub-block chain starting at *pos*."""
    while pos < len(data):
        size = data[pos]
        pos += 1
        if size == 0:
            return pos
        pos += size
    raise ValueError("truncated sub-block chain")


def _gce_delay_offsets(data: bytes | bytearray) -> List[int]:
    """Byte offsets of each Graphic Control Extension's delay field."""
    if data[:3] != b"GIF" or len(data) < 13:
        raise ValueError("not a GIF file")
    pos = 6 + 7  # header + logical screen descriptor
    flags = data[10]
    if flags & 0x80:  # global color table
        pos += 3 * (2 << (flags & 0x07))

    offsets: List[int] = []
    while pos < len(data):
        block = data[pos]
        if block == _TRAILER:
            break
        if block == _EXTENSION_INTRODUCER:
            label = data[pos + 1]
            if label == _GRAPHIC_CONTROL_LABEL:
                # introducer, label, block size byte, packed flags → delay
                offsets.append(pos + 4)
            pos = _skip_sub_blocks(data, pos + 2)
        elif block == _IMAGE_SEPARATOR:
            pos += 9  # separator + position/size
            local_flags = data[pos]
            pos += 1
            if local_flags & 0x80:  # local color table
                pos += 3 * (2 << (local_flags & 0x07))
            pos += 1  # LZW minimum code size
            pos = _skip_sub_blocks(data, pos)
        else:
            raise ValueError(f"unknown GIF block 0x{block:02x} at offset {pos}")
    return offsets


def rewrite_gif_delays(path: Path, delays_cs: Sequence[int]) -> bool:
    """Set the *k*-th frame's delay to ``delays_cs[k]``, in place.

    Returns False (leaving the file untouched) if the file's frame count does
    not match — the ffmpeg-written timing stays, which is correct on average.
    """
    data = bytearray(path.read_bytes())
    try:
        offsets = _gce_delay_offsets(data)
    except (ValueError, IndexError) as exc:
        log.warning("could not parse GIF for delay rewrite: %s", exc)
        return False
    if len(offsets) != len(delays_cs):
        log.warning(
            "GIF delay rewrite skipped: %d frames in file, %d delays",
            len(offsets), len(delays_cs),
        )
        return False
    for offset, cs in zip(offsets, delays_cs, strict=True):
        clamped = max(1, min(int(cs), 0xFFFF))
        data[offset] = clamped & 0xFF
        data[offset + 1] = (clamped >> 8) & 0xFF
    path.write_bytes(data)
    return True
