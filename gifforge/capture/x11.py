# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""X11 screen capture via ffmpeg ``x11grab``.

Ported from ``ffmpeg-screen-recorder.vala``. Records the area to a WebM
intermediate (quality VP9 for WebM output — passed through unchanged — and
lossless VP9 for the GIF/APNG path), which the encode pipeline then converts.
The secondary backend for GIF Forge; Wayland (portal) is primary.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import List

from ..models import OutputFormat, RecordingArea, RecordingConfig
from ..utils import check_for_executable, create_temp_file
from ..encode.errors import RecordingError
from .backend import CaptureBackend, CaptureState

log = logging.getLogger(__name__)

FFMPEG = "ffmpeg"


def build_x11grab_argv(
    area: RecordingArea, config: RecordingConfig, output_path: Path, display: str
) -> List[str]:
    """Build the ffmpeg x11grab command (faithful to Peek's ordering).

    ``-nostats -loglevel error`` keeps stderr near-empty: the recorder holds the
    pipe open without a reader thread, so a chatty stderr would fill the pipe
    buffer and deadlock ffmpeg mid-recording.
    """
    argv: List[str] = [FFMPEG, "-hide_banner", "-nostats", "-loglevel", "error"]

    if config.capture_sound and config.output_format == OutputFormat.WEBM:
        argv += ["-f", "pulse", "-i", "default", "-acodec", "vorbis"]

    argv += [
        "-f", "x11grab",
        "-show_region", "0",
        "-framerate", str(max(config.framerate, 6)),
        "-video_size", f"{area.width}x{area.height}",
    ]

    if not config.capture_mouse:
        argv += ["-draw_mouse", "0"]

    argv += ["-i", f"{display}+{area.left},{area.top}"]
    # Even output dimensions: the user-drawn region is arbitrary, and odd sizes
    # make yuv420p (WebM output) fail outright.
    ds = config.downsample
    argv += ["-filter:v", f"scale=trunc(iw/{ds}/2)*2:trunc(ih/{ds}/2)*2"]
    argv += _output_params(config)
    argv += ["-y", str(output_path)]
    return argv


def _output_params(config: RecordingConfig) -> List[str]:
    """Intermediate codec params (ported from ffmpeg.vala add_output_parameters).

    WebM output → quality VP9 (final, passed through); everything else →
    lossless VP9 webm intermediate.
    """
    if config.output_format == OutputFormat.WEBM:
        params = [
            "-codec:v", "libvpx-vp9",
            "-qmin", "10", "-qmax", "50", "-crf", "13",
            "-b:v", "1M", "-pix_fmt", "yuv420p",
        ]
    else:
        params = ["-codec:v", "libvpx-vp9", "-lossless", "1"]
    params += ["-r", str(config.framerate)]
    return params


def _decode_stderr(err: bytes | None) -> str:
    return (err or b"").decode(errors="replace").strip()


class X11Recorder(CaptureBackend):
    """Records via ffmpeg x11grab, stopped by sending 'q' to stdin (like Peek)."""

    def __init__(self, config: RecordingConfig) -> None:
        super().__init__(config)
        self._proc: subprocess.Popen | None = None

    @staticmethod
    def is_available() -> bool:
        return check_for_executable(FFMPEG) and bool(os.environ.get("DISPLAY"))

    def start(self, area: RecordingArea) -> None:
        if not area.is_valid():
            raise RecordingError("recording area has zero size")
        display = os.environ.get("DISPLAY") or ":0"
        self.temp_file = create_temp_file("webm")
        # WebM is captured at final quality; the controller passes it through
        # instead of re-encoding (a second lossy generation).
        self.intermediate_is_final = self.config.output_format == OutputFormat.WEBM
        argv = build_x11grab_argv(area, self.config, self.temp_file, display)
        log.debug("x11grab: %s", " ".join(argv))
        try:
            self._proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise RecordingError(f"failed to start ffmpeg: {exc}") from exc

        # Catch immediate failures (bad geometry, missing x11grab, …) so the
        # user sees ffmpeg's message instead of recording into the void.
        time.sleep(0.2)
        if self._proc.poll() is not None:
            _, err = self._proc.communicate()
            rc = self._proc.returncode
            self._proc = None
            self.state = CaptureState.FAILED
            detail = _decode_stderr(err)
            raise RecordingError(
                f"ffmpeg exited immediately ({rc})" + (f":\n{detail}" if detail else "")
            )
        self.state = CaptureState.RECORDING

    def stop(self) -> Path:
        if self._proc is None or self.temp_file is None:
            raise RecordingError("not recording")
        self.state = CaptureState.STOPPING
        proc = self._proc
        self._proc = None
        err: bytes | None = b""
        try:
            # Graceful stop: ffmpeg finalizes the file when it reads 'q'.
            _, err = proc.communicate(input=b"q", timeout=15)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                _, err = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        rc = proc.returncode
        if rc not in (0, 255):  # 255 = ffmpeg's normal 'q' exit on some builds
            self.state = CaptureState.FAILED
            detail = _decode_stderr(err)
            raise RecordingError(
                f"ffmpeg exited with {rc}" + (f":\n{detail}" if detail else "")
            )
        self.state = CaptureState.DONE
        return self.temp_file

    def cancel(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._proc.wait()
            self._proc = None
        if self.temp_file is not None:
            self.temp_file.unlink(missing_ok=True)
            self.temp_file = None
        self.state = CaptureState.IDLE
