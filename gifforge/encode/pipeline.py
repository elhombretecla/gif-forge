# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""High-level encode pipeline: pick the right path for a given config.

Mirrors Peek's ``BaseScreenRecorder.build_post_processor_pipeline`` priority:
GIF via gifski (if enabled & available) else ffmpeg 2-pass; WebM passthrough/
re-encode; APNG via ffmpeg 2-pass.
"""

from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path

from ..frames.deglitch import find_capture_glitches
from ..models import OutputFormat, RecordingConfig
from . import ffmpeg, gifski

log = logging.getLogger(__name__)


def encode_recording(
    input_path: Path,
    config: RecordingConfig,
    *,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Encode the raw recording at *input_path* into the configured format.

    Returns the path to the produced file (a temp file the caller owns).
    Backends whose intermediate already *is* the final format (see
    ``CaptureBackend.intermediate_is_final``) skip this entirely — the
    controller passes the intermediate through, avoiding a second lossy encode.
    """
    config.validate()
    fps = config.framerate
    fmt = config.output_format

    if fmt == OutputFormat.WEBM:
        return ffmpeg.encode_webm(input_path, fps, cancel_event=cancel_event)

    # GIF and APNG re-encode the intermediate frame by frame, so capture
    # glitches (frames/deglitch.py) can be repaired on the way through.
    glitches = find_capture_glitches(input_path, cancel_event=cancel_event)

    if fmt == OutputFormat.APNG:
        log.debug("encoding APNG directly (true colour, no palette)")
        return ffmpeg.encode_apng(
            input_path, fps, drop_frames=glitches, cancel_event=cancel_event
        )

    if config.gifski_enabled and gifski.is_available():
        frames = ffmpeg.extract_frames(input_path, cancel_event=cancel_event)
        try:
            if gifski.frames_within_argv_limit(frames):
                for i in glitches:
                    if i < len(frames):
                        shutil.copyfile(frames[i - 1] if i > 0 else frames[i + 1], frames[i])
                log.debug("encoding GIF via gifski (%d frames)", len(frames))
                return gifski.encode_gif(
                    frames, fps, config.gifski_quality, cancel_event=cancel_event
                )
            log.warning(
                "recording too long for gifski (%d frames); falling back to ffmpeg",
                len(frames),
            )
        finally:
            for frame in frames:
                frame.unlink(missing_ok=True)

    log.debug("encoding GIF via ffmpeg 2-pass")
    return ffmpeg.encode_gif(
        input_path, fps, drop_frames=glitches, cancel_event=cancel_event
    )
