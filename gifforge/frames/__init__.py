# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Frame processing: decode a recording into an editable, disk-backed model."""

from .decode import decode_to_frames
from .model import Frame, FrameList

__all__ = ["Frame", "FrameList", "decode_to_frames"]
