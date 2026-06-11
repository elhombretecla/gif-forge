# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Named, undoable edit operations.

Each :class:`Command` only implements the forward mutation via ``apply``; the
:class:`~gifforge.editor.timeline.Timeline` snapshots the frame list before
applying and restores it on undo, so undo/redo is correct for every command —
structural (delete/dedup/trim/crop) and in-place (delay) alike — without each
command needing bespoke inverse logic.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, List

from ..frames.model import Frame, FrameList


class Command:
    label = "Edit"

    def apply(self, frames: FrameList) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


class InsertFrames(Command):
    """Insert frames (e.g. a paste) starting at *index*."""

    label = "Insert frames"

    def __init__(self, index: int, frames: Iterable[Frame]) -> None:
        self.index = index
        self._frames: List[Frame] = [f.clone() for f in frames]

    def apply(self, frames: FrameList) -> None:
        for offset, frame in enumerate(self._frames):
            frames.insert(self.index + offset, frame.clone())


class ReplaceFrames(Command):
    """Replace the whole frame list (used by Reset)."""

    label = "Reset"

    def __init__(self, frames: Iterable[Frame]) -> None:
        self._frames: List[Frame] = [f.clone() for f in frames]

    def apply(self, frames: FrameList) -> None:
        frames.replace_all(f.clone() for f in self._frames)


class DeleteFrames(Command):
    label = "Delete frames"

    def __init__(self, indices: Iterable[int]) -> None:
        self.indices = sorted(set(indices))

    def apply(self, frames: FrameList) -> None:
        for i in reversed(self.indices):
            frames.remove_at(i)


class DuplicateFrames(Command):
    label = "Duplicate frames"

    def __init__(self, indices: Iterable[int]) -> None:
        self.indices = sorted(set(indices))

    def apply(self, frames: FrameList) -> None:
        # Descending so each insertion does not shift not-yet-processed indices.
        for i in reversed(self.indices):
            frames.duplicate(i)


class MoveFrame(Command):
    label = "Move frame"

    def __init__(self, src: int, dst: int) -> None:
        self.src = src
        self.dst = dst

    def apply(self, frames: FrameList) -> None:
        frames.move(self.src, self.dst)


class ReverseFrames(Command):
    label = "Reverse"

    def apply(self, frames: FrameList) -> None:
        frames.reverse()


class SetDelay(Command):
    label = "Set delay"

    def __init__(self, indices: Iterable[int], delay_ms: int) -> None:
        self.indices = list(indices)
        self.delay_ms = delay_ms

    def apply(self, frames: FrameList) -> None:
        for i in self.indices:
            frames.set_delay(i, self.delay_ms)


class AdjustDelay(Command):
    label = "Adjust delay"

    def __init__(self, indices: Iterable[int], delta_ms: int) -> None:
        self.indices = list(indices)
        self.delta_ms = delta_ms

    def apply(self, frames: FrameList) -> None:
        for i in self.indices:
            frames.set_delay(i, frames[i].delay_ms + self.delta_ms)


class ScaleDelay(Command):
    """Change playback speed of selected frames (factor < 1 = faster)."""

    label = "Change speed"

    def __init__(self, indices: Iterable[int], factor: float) -> None:
        if factor <= 0:
            raise ValueError("speed factor must be positive")
        self.indices = list(indices)
        self.factor = factor

    def apply(self, frames: FrameList) -> None:
        for i in self.indices:
            frames.set_delay(i, max(1, round(frames[i].delay_ms * self.factor)))


class TrimFrames(Command):
    label = "Trim"

    def __init__(self, start: int, end: int) -> None:
        self.start = start
        self.end = end

    def apply(self, frames: FrameList) -> None:
        frames.trim(self.start, self.end)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class RemoveDuplicates(Command):
    """Merge runs of consecutive identical frames, folding their delays in."""

    label = "Remove duplicates"

    def apply(self, frames: FrameList) -> None:
        merged: List = []
        prev_hash = None
        # Duplicated frames share their source PNG; hash each path once instead
        # of re-reading the file for every occurrence.
        hashes: dict[str, str] = {}
        for frame in frames.to_list():
            key = str(frame.path)
            digest = hashes.get(key)
            if digest is None:
                digest = hashes[key] = _file_hash(frame.path)
            if digest == prev_hash and merged:
                merged[-1].delay_ms += frame.delay_ms
            else:
                merged.append(frame)
                prev_hash = digest
        frames.replace_all(merged)


class ReduceFrames(Command):
    """Keep every Nth frame, folding dropped frames' delays into the kept one."""

    label = "Reduce frames"

    def __init__(self, keep_every: int) -> None:
        if keep_every < 2:
            raise ValueError("keep_every must be >= 2")
        self.keep_every = keep_every

    def apply(self, frames: FrameList) -> None:
        kept: List = []
        for index, frame in enumerate(frames.to_list()):
            if index % self.keep_every == 0:
                kept.append(frame)
            elif kept:
                kept[-1].delay_ms += frame.delay_ms
        frames.replace_all(kept)


class CropFrames(Command):
    """Crop every frame to a rectangle, producing new PNGs in the cache.

    The interactive region picker is a follow-up; the command itself is complete
    and tested. Each unique source image is cropped once and shared.
    """

    label = "Crop"

    def __init__(self, x: int, y: int, width: int, height: int, cache) -> None:
        self.rect = (x, y, width, height)
        self.cache = cache

    def apply(self, frames: FrameList) -> None:
        from ..frames.imageops import crop_png

        cropped: dict[str, Path] = {}
        for frame in frames:
            key = str(frame.path)
            if key not in cropped:
                cropped[key] = crop_png(Path(frame.path), self.rect, self.cache)
            frame.path = cropped[key]
