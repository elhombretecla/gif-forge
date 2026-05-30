# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Composite overlays onto frames at export time using Cairo.

Returns a new FrameList whose frames point at freshly rendered PNGs (frames with
no applicable overlay are passed through unchanged). Cairo (pycairo) ships with
PyGObject and is a pure rendering dependency — no GTK needed — so this stays out
of the UI layer.
"""

from __future__ import annotations

import logging
import math
from typing import Callable, Dict, List

import cairo

from ..editor.overlays import (
    MouseClickOverlay,
    Overlay,
    TextOverlay,
    WatermarkOverlay,
)
from .model import Frame, FrameList

log = logging.getLogger(__name__)


def _render_text(ctx: cairo.Context, o: TextOverlay, index: int, w: int, h: int) -> None:
    ctx.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(o.font_size)
    # Drop shadow for legibility over any background.
    ctx.set_source_rgba(0, 0, 0, 0.6)
    ctx.move_to(o.x + 1.5, o.y + 1.5)
    ctx.show_text(o.text)
    ctx.set_source_rgba(*o.color)
    ctx.move_to(o.x, o.y)
    ctx.show_text(o.text)


def _render_click(ctx: cairo.Context, o: MouseClickOverlay, index: int, w: int, h: int) -> None:
    for frame_index, x, y in o.events:
        age = index - frame_index
        if age < 0 or age > o.trail:
            continue
        fade = 1.0 - (age / (o.trail + 1))
        r, g, b, a = o.color
        ctx.set_source_rgba(r, g, b, max(0.0, a * fade))
        ctx.arc(x, y, o.radius * (1 + age * 0.5), 0, 2 * math.pi)
        ctx.fill()


def _render_watermark(ctx: cairo.Context, o: WatermarkOverlay, index: int, w: int, h: int) -> None:
    image = cairo.ImageSurface.create_from_png(o.image_path)
    ctx.set_source_surface(image, o.x, o.y)
    ctx.paint_with_alpha(o.opacity)


_RENDERERS: Dict[type, Callable] = {
    TextOverlay: _render_text,
    MouseClickOverlay: _render_click,
    WatermarkOverlay: _render_watermark,
}


def render_overlays(frames: FrameList, overlays: List[Overlay], cache) -> FrameList:
    """Return a FrameList with *overlays* composited onto the relevant frames."""
    if not overlays:
        return frames
    n = len(frames)
    out: List[Frame] = []
    for index, frame in enumerate(frames):
        applicable = [o for o in overlays if o.applies_to(index, n)]
        if not applicable:
            out.append(frame.clone())
            continue
        surface = cairo.ImageSurface.create_from_png(str(frame.path))
        ctx = cairo.Context(surface)
        for overlay in applicable:
            renderer = _RENDERERS.get(type(overlay))
            if renderer is not None:
                renderer(ctx, overlay, index, surface.get_width(), surface.get_height())
        out_path = cache.frames_dir / f"ov_{index:05d}.png"
        surface.write_to_png(str(out_path))
        out.append(Frame(out_path, frame.delay_ms, frame.source_index))
    log.debug("rendered overlays onto %d frames", n)
    return FrameList(out)
