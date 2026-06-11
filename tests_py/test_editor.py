# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for edit commands and Timeline undo/redo correctness."""

import shutil
import subprocess
from pathlib import Path

import pytest

from gifforge.editor import (
    AdjustDelay,
    DeleteFrames,
    DuplicateFrames,
    InsertFrames,
    MoveFrame,
    ReduceFrames,
    RemoveDuplicates,
    ReverseFrames,
    ScaleDelay,
    SetDelay,
    Timeline,
    TrimFrames,
)
from gifforge.frames.model import Frame, FrameList


def make_frames(n, delay=100):
    return FrameList(Frame(Path(f"/f{i}.png"), delay, i) for i in range(n))


def order(frames):
    return [f.source_index for f in frames]


def delays(frames):
    return [f.delay_ms for f in frames]


def roundtrip(timeline, snapshot_before):
    """Undo then redo; assert state returns to snapshot_before after undo."""
    after = (order(timeline.frames), delays(timeline.frames))
    timeline.undo()
    assert (order(timeline.frames), delays(timeline.frames)) == snapshot_before
    timeline.redo()
    assert (order(timeline.frames), delays(timeline.frames)) == after


def test_delete_undo_redo():
    tl = Timeline(make_frames(5))
    before = (order(tl.frames), delays(tl.frames))
    tl.execute(DeleteFrames([1, 3]))
    assert order(tl.frames) == [0, 2, 4]
    roundtrip(tl, before)


def test_duplicate_undo_redo():
    tl = Timeline(make_frames(3))
    before = (order(tl.frames), delays(tl.frames))
    tl.execute(DuplicateFrames([0, 2]))
    assert order(tl.frames) == [0, 0, 1, 2, 2]
    roundtrip(tl, before)


def test_move_undo_redo():
    tl = Timeline(make_frames(4))
    before = (order(tl.frames), delays(tl.frames))
    tl.execute(MoveFrame(0, 2))
    assert order(tl.frames) == [1, 2, 0, 3]
    roundtrip(tl, before)


def test_reverse_undo_redo():
    tl = Timeline(make_frames(4))
    before = (order(tl.frames), delays(tl.frames))
    tl.execute(ReverseFrames())
    assert order(tl.frames) == [3, 2, 1, 0]
    roundtrip(tl, before)


def test_set_delay_undo_is_not_noop():
    # The bug guard: in-place delay edits must be reversible.
    tl = Timeline(make_frames(3, delay=100))
    tl.execute(SetDelay([0, 1, 2], 250))
    assert delays(tl.frames) == [250, 250, 250]
    tl.undo()
    assert delays(tl.frames) == [100, 100, 100]
    tl.redo()
    assert delays(tl.frames) == [250, 250, 250]


def test_adjust_and_scale_delay():
    tl = Timeline(make_frames(2, delay=100))
    tl.execute(AdjustDelay([0, 1], 50))
    assert delays(tl.frames) == [150, 150]
    tl.execute(ScaleDelay([0, 1], 2.0))
    assert delays(tl.frames) == [300, 300]
    tl.undo()
    assert delays(tl.frames) == [150, 150]
    tl.undo()
    assert delays(tl.frames) == [100, 100]


def test_trim_undo_redo():
    tl = Timeline(make_frames(6))
    before = (order(tl.frames), delays(tl.frames))
    tl.execute(TrimFrames(2, 4))
    assert order(tl.frames) == [2, 3, 4]
    roundtrip(tl, before)


def test_reduce_frames_folds_delays():
    tl = Timeline(make_frames(4, delay=100))
    before = (order(tl.frames), delays(tl.frames))
    tl.execute(ReduceFrames(2))  # keep indices 0,2; fold 1->0, 3->2
    assert order(tl.frames) == [0, 2]
    assert delays(tl.frames) == [200, 200]
    roundtrip(tl, before)


def test_insert_frames_paste_undo_redo():
    tl = Timeline(make_frames(3))
    before = (order(tl.frames), delays(tl.frames))
    pasted = [Frame(Path("/p1.png"), 50, 99), Frame(Path("/p2.png"), 60, 98)]
    tl.execute(InsertFrames(1, pasted))
    assert [f.source_index for f in tl.frames] == [0, 99, 98, 1, 2]
    roundtrip(tl, before)


def test_reset_reverts_all_edits():
    tl = Timeline(make_frames(4, delay=100))
    tl.execute(DeleteFrames([0, 1]))
    tl.execute(ScaleDelay([0], 2.0))
    assert len(tl.frames) == 2
    tl.reset()
    assert [f.source_index for f in tl.frames] == [0, 1, 2, 3]
    assert delays(tl.frames) == [100, 100, 100, 100]
    # Reset is itself undoable.
    tl.undo()
    assert len(tl.frames) == 2


def test_history_flags_and_redo_cleared_on_new_edit():
    tl = Timeline(make_frames(3))
    assert not tl.can_undo and not tl.can_redo
    tl.execute(DeleteFrames([0]))
    assert tl.can_undo and not tl.can_redo
    tl.undo()
    assert tl.can_redo
    tl.execute(ReverseFrames())  # new edit clears redo
    assert not tl.can_redo


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_remove_duplicates_real_files(tmp_path):
    # Three frames where 0 and 1 are byte-identical, 2 differs.
    a = tmp_path / "a.png"
    c = tmp_path / "c.png"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "color=c=red:s=16x16:d=1", "-frames:v", "1", str(a)],
                   check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "color=c=blue:s=16x16:d=1", "-frames:v", "1", str(c)],
                   check=True, capture_output=True)
    b = tmp_path / "b.png"
    shutil.copy(a, b)  # identical bytes to a

    frames = FrameList([
        Frame(a, 100, 0), Frame(b, 100, 1), Frame(c, 100, 2),
    ])
    tl = Timeline(frames)
    before = (order(tl.frames), delays(tl.frames))
    tl.execute(RemoveDuplicates())
    assert len(tl.frames) == 2  # a(+b merged), c
    assert delays(tl.frames) == [200, 100]
    tl.undo()
    assert (order(tl.frames), delays(tl.frames)) == before


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_crop_command_and_undo(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    import importlib
    from gifforge import utils as utils_mod
    importlib.reload(utils_mod)
    from gifforge.project import cache as cache_mod
    importlib.reload(cache_mod)
    from gifforge.editor.commands import CropFrames

    src = tmp_path / "src.png"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    "testsrc=s=100x80:d=1", "-frames:v", "1", str(src)],
                   check=True, capture_output=True)

    cache = cache_mod.SessionCache()
    frames = FrameList([Frame(src, 100, 0), Frame(src, 100, 1)])
    tl = Timeline(frames)
    original_path = frames[0].path

    tl.execute(CropFrames(10, 10, 40, 30, cache))
    cropped = frames[0].path
    assert cropped != original_path
    # Both frames shared the same source -> cropped once, shared result.
    assert frames[0].path == frames[1].path
    # Verify cropped dimensions via ffprobe.
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(cropped)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert out == "40,30"

    tl.undo()
    assert frames[0].path == original_path  # undo restores the source path
    cache.cleanup()
