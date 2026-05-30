# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""High-level encode pipeline: pick the right path for a given config.

Mirrors Peek's ``BaseScreenRecorder.build_post_processor_pipeline`` priority:
GIF via gifski (if enabled & available) else ffmpeg 2-pass; WebM passthrough/
re-encode; APNG via ffmpeg 2-pass.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from ..models import OutputFormat, RecordingConfig
from . import ffmpeg, gifski

log = logging.getLogger(__name__)


def encode_recording(
    input_path: Path,
    config: RecordingConfig,
    *,
    cancel_event: Optional[threading.Event] = None,
) -> Path:
    """Encode the raw recording at *input_path* into the configured format.

    Returns the path to the produced file (a temp file the caller owns).
    """
    config.validate()
    fps = config.framerate
    fmt = config.output_format

    if fmt == OutputFormat.WEBM:
        return ffmpeg.encode_webm(input_path, fps, cancel_event=cancel_event)

    if fmt == OutputFormat.GIF and config.gifski_enabled and gifski.is_available():
        log.debug("encoding GIF via gifski")
        frames = ffmpeg.extract_frames(input_path, cancel_event=cancel_event)
        try:
            return gifski.encode_gif(
                frames, fps, config.gifski_quality, cancel_event=cancel_event
            )
        finally:
            for frame in frames:
                frame.unlink(missing_ok=True)

    # GIF (ffmpeg 2-pass) or APNG.
    log.debug("encoding %s via ffmpeg 2-pass", fmt.value)
    return ffmpeg.encode_gif_or_apng(
        input_path, fps, output_format=fmt, cancel_event=cancel_event
    )
