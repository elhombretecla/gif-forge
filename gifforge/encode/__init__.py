# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Encoding / export pipeline.

Re-implements Peek's ``post-processing`` package in Python: thin, faithful
orchestration of ffmpeg and gifski. The exact command-line flags are ported
from the original Vala so output quality matches or exceeds Peek.
"""

from .errors import EncodeError
from .frames_export import export_frames
from .pipeline import encode_recording
from .presets import DEFAULT_PRESETS, ExportPreset, default_preset_for

__all__ = [
    "EncodeError",
    "encode_recording",
    "export_frames",
    "ExportPreset",
    "DEFAULT_PRESETS",
    "default_preset_for",
]
