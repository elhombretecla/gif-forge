# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Project/session persistence and cache management.

For now this provides the per-session cache used by the editor (decoded frames
on disk). Project-file save/reopen and recovery land in T11.
"""

from .cache import SessionCache
from .document import PROJECT_SUFFIX, PROJECT_VERSION, ProjectDocument
from .store import (
    ProjectError,
    RecentProjects,
    autosave,
    clear_autosave,
    list_recoverable,
    load_project,
    save_project,
)

__all__ = [
    "SessionCache",
    "ProjectDocument",
    "PROJECT_SUFFIX",
    "PROJECT_VERSION",
    "ProjectError",
    "RecentProjects",
    "save_project",
    "load_project",
    "autosave",
    "clear_autosave",
    "list_recoverable",
]
