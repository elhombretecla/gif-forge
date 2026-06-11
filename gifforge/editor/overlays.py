# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Overlay-task model (text captions, mouse-click markers, watermarks).

Overlays are *non-destructive*: they're stored on the timeline/project and only
composited onto frames at export time (see
:mod:`gifforge.frames.overlay_render`). The model here is pure data — no Cairo
or GTK — so it serializes into the project file and is unit-testable.

This is the extensible "task" concept adapted from ScreenToGif. Mouse-click and
keystroke overlays would normally be fed by input captured during recording;
that capture (hard on Wayland) is deferred, but the rendering is complete and
can be driven by externally supplied events.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import ClassVar, List, Tuple

Color = Tuple[float, float, float, float]  # r, g, b, a in 0..1


@dataclass
class Overlay:
    start: int = 0
    end: int = -1  # inclusive; -1 means "through the last frame"

    KIND: ClassVar[str] = "overlay"

    def applies_to(self, index: int, n: int) -> bool:
        end = self.end if self.end >= 0 else n - 1
        return self.start <= index <= end

    def to_dict(self) -> dict:
        data = asdict(self)
        data["kind"] = self.KIND
        return data


@dataclass
class TextOverlay(Overlay):
    text: str = ""
    x: int = 12
    y: int = 36
    font_size: int = 24
    color: Color = (1.0, 1.0, 1.0, 1.0)

    KIND: ClassVar[str] = "text"


@dataclass
class MouseClickOverlay(Overlay):
    # Each event is (frame_index, x, y) in device pixels.
    events: List[Tuple[int, int, int]] = field(default_factory=list)
    radius: int = 16
    color: Color = (1.0, 0.35, 0.1, 0.75)
    # Frames the ripple stays visible after the click.
    trail: int = 2

    KIND: ClassVar[str] = "click"

    def applies_to(self, index: int, n: int) -> bool:
        return any(e[0] <= index <= e[0] + self.trail for e in self.events)


@dataclass
class WatermarkOverlay(Overlay):
    image_path: str = ""
    x: int = 0
    y: int = 0
    opacity: float = 0.8

    KIND: ClassVar[str] = "watermark"


_REGISTRY = {
    cls.KIND: cls for cls in (TextOverlay, MouseClickOverlay, WatermarkOverlay)
}


def overlay_from_dict(data: dict) -> Overlay:
    if not isinstance(data, dict):
        raise ValueError(f"overlay entry must be an object, got {type(data).__name__}")
    payload = dict(data)
    kind = payload.pop("kind", "overlay")
    cls = _REGISTRY.get(kind)
    if cls is None:
        raise ValueError(f"unknown overlay kind: {kind!r}")
    # Project manifests can come from third parties: reject unexpected fields
    # instead of letting cls(**payload) raise a bare TypeError.
    allowed = {f.name for f in fields(cls)}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown overlay field(s) for {kind!r}: {unknown}")
    # JSON turns tuples into lists; normalize the ones we index positionally.
    if "events" in payload:
        payload["events"] = [tuple(e) for e in payload["events"]]
    if "color" in payload:
        payload["color"] = tuple(payload["color"])
    return cls(**payload)
