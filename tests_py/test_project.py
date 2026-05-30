# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for project save/load, recents, and autosave/recovery."""

import importlib

import pytest

from gifforge.frames.model import Frame, FrameList
from gifforge.models import OutputFormat


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from gifforge import utils as utils_mod
    importlib.reload(utils_mod)
    from gifforge.project import cache as cache_mod
    importlib.reload(cache_mod)
    from gifforge.project import store as store_mod
    importlib.reload(store_mod)
    from gifforge.project import document as doc_mod
    importlib.reload(doc_mod)
    return store_mod, cache_mod, doc_mod, tmp_path


def _make_png(path, color="red"):
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                    f"color=c={color}:s=32x24:d=1", "-frames:v", "1", str(path)],
                   check=True, capture_output=True)
    return path


def test_save_load_roundtrip(env):
    store, cache_mod, doc_mod, tmp = env
    import shutil
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")

    a = _make_png(tmp / "a.png", "red")
    b = _make_png(tmp / "b.png", "blue")
    # Frame 'a' is duplicated (shares path) — should be stored once.
    frames = FrameList([
        Frame(a, 120, 0), Frame(a, 120, 0), Frame(b, 350, 1),
    ])
    doc = doc_mod.ProjectDocument(frames, output_format=OutputFormat.WEBM)

    dest = tmp / "myproj.gifforge"
    store.save_project(doc, dest)
    assert dest.exists()

    cache = cache_mod.SessionCache()
    loaded = store.load_project(dest, cache)
    assert len(loaded.frames) == 3
    assert [f.delay_ms for f in loaded.frames] == [120, 120, 350]
    assert loaded.output_format is OutputFormat.WEBM
    assert loaded.created  # timestamp set on save
    # Duplicated frame extracted to a single shared file.
    paths = [str(f.path) for f in loaded.frames]
    assert paths[0] == paths[1] != paths[2]
    assert all(f.path.exists() for f in loaded.frames)


def test_rejects_unknown_version(env):
    store, cache_mod, doc_mod, tmp = env
    import json, zipfile
    bad = tmp / "bad.gifforge"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("project.json", json.dumps({"version": 999, "frames": []}))
    with pytest.raises(store.ProjectError):
        store.load_project(bad)


def test_recents_add_dedup_and_prune(env):
    store, cache_mod, doc_mod, tmp = env
    recents = store.RecentProjects(limit=3)
    p1 = tmp / "1.gifforge"; p1.write_text("x")
    p2 = tmp / "2.gifforge"; p2.write_text("x")
    recents.add(p1)
    recents.add(p2)
    recents.add(p1)  # moves p1 to front, no duplicate
    listed = recents.list()
    assert listed[0] == p1.resolve()
    assert len(listed) == 2
    # Missing files are pruned.
    p2.unlink()
    assert recents.list() == [p1.resolve()]


def test_autosave_recover_and_clear(env):
    store, cache_mod, doc_mod, tmp = env
    import shutil
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    a = _make_png(tmp / "a.png")
    doc = doc_mod.ProjectDocument(FrameList([Frame(a, 100, 0)]))

    assert store.list_recoverable() == []
    store.autosave(doc, "session-1")
    recoverable = store.list_recoverable()
    assert len(recoverable) == 1

    # The autosave is itself a valid, loadable project.
    restored = store.load_project(recoverable[0], cache_mod.SessionCache())
    assert len(restored.frames) == 1

    store.clear_autosave("session-1")
    assert store.list_recoverable() == []
