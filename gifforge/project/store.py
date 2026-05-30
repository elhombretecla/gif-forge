# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Project persistence: the ``.gifforge`` container, recents, and autosave.

Container layout (a zip archive):

    project.json          # manifest (version, frames, output format, metadata)
    frames/00001.png      # one PNG per *unique* source frame
    ...

Duplicated frames (which share a source PNG) are stored once and referenced
multiple times in the manifest, so projects stay compact. The manifest carries
a ``version`` so future format changes can be detected and rejected cleanly.
"""

from __future__ import annotations

import json
import logging
import time
import zipfile
from pathlib import Path
from typing import List, Optional

from ..frames.model import Frame, FrameList
from ..models import OutputFormat
from ..utils import cache_dir
from .cache import SessionCache
from .document import PROJECT_VERSION, ProjectDocument

log = logging.getLogger(__name__)

_MANIFEST = "project.json"


class ProjectError(Exception):
    pass


# --- save / load --------------------------------------------------------------


def save_project(document: ProjectDocument, dest: Path) -> Path:
    """Write *document* to *dest* as a ``.gifforge`` container."""
    dest = Path(dest)
    if not document.created:
        document.created = time.strftime("%Y-%m-%dT%H:%M:%S")

    archive_names: dict[str, str] = {}
    manifest_frames: List[dict] = []

    # Write to a temp file then move, so an interrupted save can't corrupt dest.
    tmp = dest.with_name(dest.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
        for frame in document.frames:
            src = str(frame.path)
            if src not in archive_names:
                name = f"frames/{len(archive_names) + 1:05d}.png"
                archive_names[src] = name
                archive.write(src, name)
            manifest_frames.append({
                "file": archive_names[src],
                "delay_ms": frame.delay_ms,
                "source_index": frame.source_index,
            })
        manifest = {
            "version": PROJECT_VERSION,
            "app": "GIF Forge",
            "created": document.created,
            "output_format": document.output_format.value,
            "frames": manifest_frames,
            "overlays": [o.to_dict() for o in document.overlays],
            "metadata": document.metadata,
        }
        archive.writestr(_MANIFEST, json.dumps(manifest, indent=2))

    tmp.replace(dest)
    document.path = dest
    log.info("saved project %s (%d frames)", dest, len(document.frames))
    return dest


def load_project(path: Path, cache: Optional[SessionCache] = None) -> ProjectDocument:
    """Load a ``.gifforge`` container, extracting frames into *cache*."""
    path = Path(path)
    cache = cache or SessionCache()
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read(_MANIFEST))
            version = manifest.get("version")
            if version != PROJECT_VERSION:
                raise ProjectError(
                    f"unsupported project version {version} "
                    f"(this build understands {PROJECT_VERSION})"
                )
            extracted: dict[str, Path] = {}
            frames: List[Frame] = []
            for entry in manifest["frames"]:
                arc = entry["file"]
                if arc not in extracted:
                    out = cache.frames_dir / Path(arc).name
                    out.write_bytes(archive.read(arc))
                    extracted[arc] = out
                frames.append(
                    Frame(extracted[arc], entry["delay_ms"], entry["source_index"])
                )
    except (KeyError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ProjectError(f"not a valid GIF Forge project: {exc}") from exc

    from ..editor.overlays import overlay_from_dict

    overlays = [overlay_from_dict(o) for o in manifest.get("overlays", [])]
    return ProjectDocument(
        frames=FrameList(frames),
        output_format=OutputFormat.from_value(manifest.get("output_format", "gif")),
        created=manifest.get("created", ""),
        path=path,
        overlays=overlays,
        metadata=manifest.get("metadata", {}),
    )


# --- recent projects ----------------------------------------------------------


class RecentProjects:
    def __init__(self, path: Optional[Path] = None, limit: int = 10) -> None:
        self._path = path or (_config_dir() / "recents.json")
        self._limit = limit

    def add(self, project_path: Path) -> None:
        items = [str(Path(project_path).resolve())]
        for existing in self._read():
            if existing not in items:
                items.append(existing)
        self._write(items[: self._limit])

    def list(self) -> List[Path]:
        """Existing recent projects, most-recent first; prunes missing files."""
        result = [Path(p) for p in self._read() if Path(p).exists()]
        # Rewrite if any were pruned.
        if len(result) != len(self._read()):
            self._write([str(p) for p in result])
        return result

    def _read(self) -> List[str]:
        try:
            return json.loads(self._path.read_text())
        except (OSError, ValueError):
            return []

    def _write(self, items: List[str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(items, indent=2))


# --- autosave / crash recovery ------------------------------------------------


def _config_dir() -> Path:
    import os

    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    from .. import APP_ID

    path = Path(base) / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def autosave_dir() -> Path:
    path = cache_dir() / "autosave"
    path.mkdir(parents=True, exist_ok=True)
    return path


def autosave(document: ProjectDocument, session_id: str) -> Path:
    """Write a recovery snapshot for *session_id* (cleared on clean close)."""
    return save_project(document, autosave_dir() / f"{session_id}.gifforge")


def clear_autosave(session_id: str) -> None:
    (autosave_dir() / f"{session_id}.gifforge").unlink(missing_ok=True)


def list_recoverable() -> List[Path]:
    """Autosave snapshots left behind by a previous (crashed) session."""
    return sorted(autosave_dir().glob("*.gifforge"))
