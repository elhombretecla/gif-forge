# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Small cross-cutting helpers (temp files, executable lookup).

Replaces the grab-bag of helpers in Peek's utils.vala using the Python stdlib.
The Linux-specific ``/proc/meminfo`` parsing is intentionally dropped.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

from . import APP_ID

_TEMP_PREFIX = "gif-forge-"

# Leftovers from crashed sessions older than this are swept at startup.
_STALE_TEMP_AGE_SECONDS = 2 * 24 * 3600


def check_for_executable(name: str) -> bool:
    """Return True if *name* is found on PATH."""
    return shutil.which(name) is not None


def cache_dir() -> Path:
    """Per-app cache directory under XDG_CACHE_HOME."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    path = Path(base) / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_temp_file(extension: str) -> Path:
    """Create an empty temp file with *extension*, returning its path.

    The caller owns the file's lifecycle. Lives under the app cache dir so
    cleanup/recovery policies can find leftovers.
    """
    fd, name = tempfile.mkstemp(
        prefix=_TEMP_PREFIX, suffix=f".{extension}", dir=str(cache_dir())
    )
    os.close(fd)
    return Path(name)


def create_temp_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX, dir=str(cache_dir())))


def cleanup_stale_temp_files(max_age_seconds: int = _STALE_TEMP_AGE_SECONDS) -> int:
    """Sweep temp files/dirs left behind by crashed sessions.

    Lossless intermediates can be hundreds of MB, so leftovers accumulate fast.
    Only entries matching our temp prefix are touched (autosave snapshots live
    under ``autosave/`` and are never matched). Returns how many were removed.
    """
    cutoff = time.time() - max_age_seconds
    removed = 0
    for entry in cache_dir().glob(_TEMP_PREFIX + "*"):
        try:
            if entry.stat().st_mtime >= cutoff:
                continue
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return removed
