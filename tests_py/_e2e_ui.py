# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Manual end-to-end UI driver (run under an X11 display).

Launches the recorder window, verifies region extraction, then drives a full
record -> encode -> save cycle with the save dialog intercepted.
"""
import shutil
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib

from gifforge.ui.application import GifForgeApplication
from gifforge.models import RecordingConfig, OutputFormat

DEST = Path("/tmp/gifforge-e2e.gif")
state = {"area_ok": False, "saved": False, "error": None}


def main():
    DEST.unlink(missing_ok=True)
    app = GifForgeApplication()

    def on_activate(_a):
        win = app.props.active_window

        # Validate the quick-save path: disable the open-editor-after-recording flow.
        win._settings.set("interface-open-editor-after-recording", False)
        # Force no countdown + GIF + low fps for a quick cycle.
        win._build_config = lambda: RecordingConfig(
            output_format=OutputFormat.GIF, framerate=8, start_delay=0
        )

        def fake_save(output):
            shutil.copy(str(output), DEST)
            Path(output).unlink(missing_ok=True)
            state["saved"] = DEST.exists()
            win._reset_idle_ui()
            app.quit()
        win._show_save_dialog = fake_save

        def after_mapped():
            try:
                area = win._extract_area()
                print(f"extracted area: left={area.left} top={area.top} "
                      f"w={area.width} h={area.height}")
                state["area_ok"] = area.is_valid()
            except Exception as exc:  # noqa: BLE001
                state["error"] = f"extract_area: {exc}"
                app.quit()
                return False
            win.toggle_recording()  # start (delay 0)
            GLib.timeout_add(1500, stop_recording)
            return False

        def stop_recording():
            win.toggle_recording()  # stop -> encode -> fake_save
            return False

        GLib.timeout_add(1200, after_mapped)

    app.connect_after("activate", on_activate)
    GLib.timeout_add_seconds(20, app.quit)  # safety net
    app.run([])

    print("area_ok:", state["area_ok"])
    print("saved:", state["saved"], "->", DEST if DEST.exists() else "(missing)")
    print("error:", state["error"])
    raise SystemExit(0 if (state["area_ok"] and state["saved"] and not state["error"]) else 1)


if __name__ == "__main__":
    main()
