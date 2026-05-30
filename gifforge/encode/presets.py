# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export presets.

A minimal, first-class preset model the export dialog renders. Phase 4 extends
this with palette/dither/scale/quality knobs and user-saved presets; for now a
preset pairs an output format with the loop choice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ..models import OutputFormat


@dataclass(frozen=True)
class ExportPreset:
    name: str
    output_format: OutputFormat
    loop: bool = True


DEFAULT_PRESETS: List[ExportPreset] = [
    ExportPreset("GIF — looping", OutputFormat.GIF, loop=True),
    ExportPreset("GIF — play once", OutputFormat.GIF, loop=False),
    ExportPreset("APNG — looping", OutputFormat.APNG, loop=True),
    ExportPreset("WebM video", OutputFormat.WEBM, loop=False),
]


def default_preset_for(output_format: OutputFormat) -> ExportPreset:
    for preset in DEFAULT_PRESETS:
        if preset.output_format == output_format:
            return preset
    return DEFAULT_PRESETS[0]
