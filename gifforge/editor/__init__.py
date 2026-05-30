# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Editor domain model: timeline + undoable edit commands (UI-agnostic)."""

from .commands import (
    AdjustDelay,
    Command,
    CropFrames,
    DeleteFrames,
    DuplicateFrames,
    InsertFrames,
    MoveFrame,
    ReduceFrames,
    RemoveDuplicates,
    ReplaceFrames,
    ReverseFrames,
    ScaleDelay,
    SetDelay,
    TrimFrames,
)
from .overlays import (
    MouseClickOverlay,
    Overlay,
    TextOverlay,
    WatermarkOverlay,
    overlay_from_dict,
)
from .timeline import Timeline

__all__ = [
    "Command",
    "DeleteFrames",
    "DuplicateFrames",
    "MoveFrame",
    "ReverseFrames",
    "RemoveDuplicates",
    "ReduceFrames",
    "SetDelay",
    "AdjustDelay",
    "ScaleDelay",
    "TrimFrames",
    "CropFrames",
    "InsertFrames",
    "ReplaceFrames",
    "Timeline",
    "Overlay",
    "TextOverlay",
    "MouseClickOverlay",
    "WatermarkOverlay",
    "overlay_from_dict",
]
