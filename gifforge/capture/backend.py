# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Abstract capture backend contract.

Equivalent to Peek's ``ScreenRecorder`` interface + ``BaseScreenRecorder``,
but framework-agnostic. A backend records the configured area to a temporary
intermediate file (typically WebM) which the encode pipeline then converts to
the requested output format.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..models import RecordingArea, RecordingConfig


class CaptureState(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    STOPPING = "stopping"
    DONE = "done"
    FAILED = "failed"


class CaptureBackend(ABC):
    """Records a screen region to an intermediate video file."""

    def __init__(self, config: RecordingConfig) -> None:
        self.config = config
        self.state = CaptureState.IDLE
        self.temp_file: Optional[Path] = None

    @staticmethod
    @abstractmethod
    def is_available() -> bool:
        """Whether this backend can run in the current environment."""

    @abstractmethod
    def start(self, area: RecordingArea) -> None:
        """Begin recording *area*. Non-blocking; raises RecordingError on setup failure."""

    @abstractmethod
    def stop(self) -> Path:
        """Stop recording and return the path to the intermediate file."""

    @abstractmethod
    def cancel(self) -> None:
        """Abort recording and discard any partial output."""

    @property
    def name(self) -> str:
        return type(self).__name__
