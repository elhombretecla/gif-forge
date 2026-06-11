# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Timeline: the editable frame list plus snapshot-based undo/redo history.

``execute`` snapshots the frame list (as clones), applies a command, and pushes
the snapshot onto the undo stack. Undo/redo swap whole snapshots, which makes
the history correct regardless of how complex a command's mutation was.

Snapshots MUST be clones, not references: several commands (SetDelay, dedup,
reduce) mutate ``Frame.delay_ms`` in place, so a reference snapshot would
reflect the post-edit value and undo would be a no-op. Clones are cheap (a path
string plus two ints), so this is inexpensive even for long recordings. Each
transition clones the live state before replacing it, so no history entry ever
aliases the live frame objects.
"""

from __future__ import annotations

import logging
from typing import List, Tuple

from ..frames.model import FrameList
from .commands import Command, ReplaceFrames

log = logging.getLogger(__name__)

# A history entry is (label, cloned-snapshot-FrameList).
_Entry = Tuple[str, FrameList]


class Timeline:
    def __init__(self, frames: FrameList) -> None:
        self.frames = frames
        self._initial = frames.copy()  # for Reset
        self._undo: List[_Entry] = []
        self._redo: List[_Entry] = []

    def reset(self) -> None:
        """Revert all edits back to the originally loaded frames (undoable)."""
        self.execute(ReplaceFrames(list(self._initial)))

    # --- history state -------------------------------------------------------

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_label(self) -> str | None:
        return self._undo[-1][0] if self._undo else None

    @property
    def redo_label(self) -> str | None:
        return self._redo[-1][0] if self._redo else None

    # --- mutation ------------------------------------------------------------

    def execute(self, command: Command) -> None:
        before = self.frames.copy()
        command.apply(self.frames)
        self._undo.append((command.label, before))
        self._redo.clear()
        log.debug("executed %s (%d frames)", command.label, len(self.frames))

    def undo(self) -> str | None:
        if not self._undo:
            return None
        label, before = self._undo.pop()
        after = self.frames.copy()
        self.frames.replace_all(before)
        self._redo.append((label, after))
        return label

    def redo(self) -> str | None:
        if not self._redo:
            return None
        label, after = self._redo.pop()
        before = self.frames.copy()
        self.frames.replace_all(after)
        self._undo.append((label, before))
        return label
