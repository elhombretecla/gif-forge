# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""End-to-end capture driver: record the (Xvfb) screen for ~2s, encode to GIF.

Run under ``xvfb-run`` in CI. Exercises the real x11grab capture path and the
encode pipeline — the code with the most environment-dependent failure modes
(stderr handling, graceful 'q' stop, two-pass palette encode).
"""

import sys
import time

from gifforge.capture.x11 import X11Recorder
from gifforge.encode.pipeline import encode_recording
from gifforge.models import OutputFormat, RecordingArea, RecordingConfig


def main() -> int:
    if not X11Recorder.is_available():
        print("SKIP: ffmpeg or DISPLAY not available")
        return 0

    config = RecordingConfig(output_format=OutputFormat.GIF, framerate=10)
    recorder = X11Recorder(config)
    recorder.start(RecordingArea(0, 0, 320, 240))
    time.sleep(2.5)
    intermediate = recorder.stop()
    assert intermediate.exists(), "intermediate missing"
    assert intermediate.stat().st_size > 0, "intermediate is empty"

    output = encode_recording(intermediate, config)
    try:
        assert output.exists(), "GIF missing"
        assert output.stat().st_size > 0, "GIF is empty"
        with open(output, "rb") as fh:
            magic = fh.read(6)
        assert magic in (b"GIF87a", b"GIF89a"), f"not a GIF: {magic!r}"
        print(f"e2e capture OK: {output} ({output.stat().st_size} bytes)")
    finally:
        intermediate.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
