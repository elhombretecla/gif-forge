# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exception hierarchy for the encode/recording pipeline.

Replaces Peek's ``errordomain.vala`` (PeekError / RecordingError).
"""

from __future__ import annotations


class GifForgeError(Exception):
    """Base class for all GIF Forge domain errors."""


class EncodeError(GifForgeError):
    """A post-processing / encoding step failed."""


class RecordingError(GifForgeError):
    """A capture/recording step failed."""


class CancelledError(GifForgeError):
    """The operation was cancelled by the user."""
