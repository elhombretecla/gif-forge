# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""The in-memory representation of an editable project.

A :class:`ProjectDocument` is the frame list plus the metadata needed to
re-open it later. Serialization to/from the on-disk ``.gifforge`` container
lives in :mod:`gifforge.project.store`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..frames.model import FrameList
from ..models import OutputFormat

PROJECT_VERSION = 1
PROJECT_SUFFIX = ".gifforge"


@dataclass
class ProjectDocument:
    frames: FrameList
    output_format: OutputFormat = OutputFormat.GIF
    created: str = ""  # ISO-8601 timestamp, set on first save
    path: Optional[Path] = None  # last saved/loaded location
    overlays: list = field(default_factory=list)  # annotation overlays
    metadata: dict = field(default_factory=dict)

    @property
    def title(self) -> str:
        return self.path.stem if self.path else "Untitled"
