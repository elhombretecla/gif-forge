# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Disk-backed frame model and an ordered, mutable frame list.

A :class:`Frame` references a PNG on disk (not pixels in RAM), so a multi-minute
recording stays cheap to hold. :class:`FrameList` is the editable container the
timeline (T8) renders and the edit commands (T9) mutate; it provides the
primitive operations (insert/remove/move/duplicate/trim) that those commands
build on. Duplicated frames intentionally share the same PNG path — frame
images are immutable, so there is no need to copy files.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List


@dataclass
class Frame:
    path: Path
    delay_ms: int
    source_index: int  # position in the original recording, for reference

    def clone(self) -> "Frame":
        return copy.copy(self)


class FrameList:
    def __init__(self, frames: Iterable[Frame] | None = None) -> None:
        self._frames: List[Frame] = list(frames or [])

    # --- sequence protocol ---------------------------------------------------

    def __len__(self) -> int:
        return len(self._frames)

    def __iter__(self) -> Iterator[Frame]:
        return iter(self._frames)

    def __getitem__(self, index: int) -> Frame:
        return self._frames[index]

    # --- derived -------------------------------------------------------------

    @property
    def total_duration_ms(self) -> int:
        return sum(f.delay_ms for f in self._frames)

    def paths(self) -> List[Path]:
        return [f.path for f in self._frames]

    def copy(self) -> "FrameList":
        return FrameList(f.clone() for f in self._frames)

    def to_list(self) -> List[Frame]:
        return list(self._frames)

    def replace_all(self, frames: Iterable[Frame]) -> None:
        """Replace the entire contents (used by snapshot-based undo)."""
        self._frames = list(frames)

    # --- primitive mutations (used by edit commands) -------------------------

    def append(self, frame: Frame) -> None:
        self._frames.append(frame)

    def insert(self, index: int, frame: Frame) -> None:
        self._frames.insert(index, frame)

    def remove_at(self, index: int) -> Frame:
        return self._frames.pop(index)

    def remove_indices(self, indices: Iterable[int]) -> List[Frame]:
        """Remove several frames at once; returns them in original order."""
        keep = set(range(len(self._frames))) - set(indices)
        removed = [f for i, f in enumerate(self._frames) if i not in keep]
        self._frames = [self._frames[i] for i in sorted(keep)]
        return removed

    def move(self, src: int, dst: int) -> None:
        frame = self._frames.pop(src)
        self._frames.insert(dst, frame)

    def duplicate(self, index: int) -> Frame:
        """Insert a copy of frame *index* immediately after it (shares the PNG)."""
        dup = self._frames[index].clone()
        self._frames.insert(index + 1, dup)
        return dup

    def set_delay(self, index: int, delay_ms: int) -> None:
        self._frames[index].delay_ms = max(0, delay_ms)

    def trim(self, start: int, end: int) -> None:
        """Keep only frames in the inclusive range [start, end]."""
        if start < 0 or end >= len(self._frames) or start > end:
            raise IndexError(f"invalid trim range {start}..{end}")
        self._frames = self._frames[start : end + 1]

    def reverse(self) -> None:
        self._frames.reverse()
