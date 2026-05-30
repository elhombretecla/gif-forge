# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Recording-area geometry helpers.

Ports the clip-to-screen + HiDPI scaling logic from recording-area.vala. The
GTK-widget-specific extraction of absolute coordinates lives in the UI layer
(GTK4 surface APIs); this module stays toolkit-agnostic and unit-testable.
"""

from __future__ import annotations

from ..models import RecordingArea


def prepare_area(
    left: int,
    top: int,
    width: int,
    height: int,
    *,
    screen_width: int,
    screen_height: int,
    scale_factor: int = 1,
) -> RecordingArea:
    """Build a device-pixel :class:`RecordingArea` from logical coordinates.

    Clips to the visible screen, then multiplies by *scale_factor* for HiDPI —
    exactly the order Peek used.
    """
    area = RecordingArea(left, top, width, height)
    area = area.clipped_to(screen_width, screen_height)
    area = area.scaled(scale_factor)
    return area
