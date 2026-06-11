# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Core data models shared across capture, encoding and the UI.

These intentionally have no GTK or platform dependencies so they can be unit
tested in isolation and reused by every layer.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class OutputFormat(enum.Enum):
    """Supported export container/codecs.

    Mirrors the original Peek ``OutputFormat`` enum (``gif``/``apng``/``webm``)
    so ported encoding flags stay faithful. New formats (webp, mp4, image
    sequence) are added in later phases.
    """

    GIF = "gif"
    APNG = "apng"
    WEBM = "webm"

    @property
    def file_extension(self) -> str:
        # Matches Peek's Utils.get_file_extension_for_format mapping.
        return {
            OutputFormat.GIF: "gif",
            OutputFormat.APNG: "apng",
            OutputFormat.WEBM: "webm",
        }[self]

    @classmethod
    def from_value(cls, value: str) -> OutputFormat:
        return cls(value.lower())


@dataclass
class RecordingConfig:
    """Settings that drive a recording and its post-processing.

    Ported from Peek's ``RecordingConfig`` (recording-config.vala) plus the
    GSettings defaults in ``data/io.github.elhombretecla.GifForge.gschema.xml``.
    """

    output_format: OutputFormat = OutputFormat.GIF
    framerate: int = 10
    downsample: int = 1
    capture_mouse: bool = True
    capture_sound: bool = False
    start_delay: int = 3
    gifski_enabled: bool = False
    gifski_quality: int = 60  # 20..100

    def validate(self) -> None:
        if not 1 <= self.framerate <= 60:
            raise ValueError(f"framerate out of range: {self.framerate}")
        if not 1 <= self.downsample <= 4:
            raise ValueError(f"downsample out of range: {self.downsample}")
        if not 0 <= self.start_delay <= 60:
            raise ValueError(f"start_delay out of range: {self.start_delay}")
        if not 20 <= self.gifski_quality <= 100:
            raise ValueError(f"gifski_quality out of range: {self.gifski_quality}")


@dataclass
class RecordingArea:
    """A capture region in absolute, device (scaled) pixel coordinates.

    Ported from recording-area.vala. The struct itself is toolkit-agnostic; the
    GTK-specific construction lives in the UI/capture layers.
    """

    left: int
    top: int
    width: int
    height: int

    def clipped_to(self, screen_width: int, screen_height: int) -> RecordingArea:
        """Clip the area to the visible screen bounds (logical coordinates)."""
        left = min(max(0, self.left), screen_width)
        top = min(max(0, self.top), screen_height)
        width = self.width
        height = self.height
        if left + width > screen_width:
            width = screen_width - left
        if top + height > screen_height:
            height = screen_height - top
        return RecordingArea(left, top, width, height)

    def scaled(self, scale_factor: int) -> RecordingArea:
        """Scale logical coordinates to device pixels on HiDPI screens."""
        return RecordingArea(
            self.left * scale_factor,
            self.top * scale_factor,
            self.width * scale_factor,
            self.height * scale_factor,
        )

    def is_valid(self) -> bool:
        return self.width > 0 and self.height > 0
