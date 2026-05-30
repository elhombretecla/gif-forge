# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-session on-disk cache.

The editor keeps decoded frames as PNG files (not in RAM) so long recordings
stay memory-safe. Each editing session owns a directory under the app cache;
:meth:`cleanup` removes it. T11 builds autosave/recovery on top of this.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..utils import create_temp_dir

log = logging.getLogger(__name__)

FRAME_PATTERN = "frame_%05d.png"
FRAME_GLOB = "frame_*.png"


class SessionCache:
    def __init__(self) -> None:
        self.root: Path = create_temp_dir()
        self.frames_dir: Path = self.root / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        log.debug("session cache at %s", self.root)

    @property
    def frame_output_pattern(self) -> Path:
        """ffmpeg image2 output pattern (1-based numbering)."""
        return self.frames_dir / FRAME_PATTERN

    def list_frames(self) -> list[Path]:
        return sorted(self.frames_dir.glob(FRAME_GLOB))

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> "SessionCache":
        return self

    def __exit__(self, *_exc) -> None:
        self.cleanup()
