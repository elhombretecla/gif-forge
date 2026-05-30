# SPDX-FileCopyrightText: 2026 Juan de la Cruz García <delacruzgarciajuan@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

"""End-to-end: decode -> editor -> edit -> export dialog -> file reflects edits."""
import subprocess
import tempfile
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw, GLib

from gifforge.project.cache import SessionCache
from gifforge.frames.decode import decode_to_frames
from gifforge.ui.editor_window import EditorWindow
from gifforge.ui.export_dialog import ExportDialog

DEST = Path(tempfile.mktemp(suffix=".gif"))
state = {"ok": False, "frames_after_edit": None, "exported_frames": None}


def packets(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_packets",
         "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return int(out)


def main():
    Adw.init()
    app = Adw.Application(application_id="io.github.elhombretecla.GifForge.ExportTest")

    sample = Path(tempfile.mktemp(suffix=".webm"))
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "testsrc=duration=2:size=160x120:rate=10",
         "-codec:v", "libvpx-vp9", "-lossless", "1", str(sample)],
        check=True, capture_output=True,
    )
    cache = SessionCache()
    frames = decode_to_frames(sample, 10, cache)
    print("decoded:", len(frames))

    def on_activate(_a):
        win = EditorWindow(application=app)
        win.present()
        win.load(frames)

        def edit_and_export():
            win.reduce_frames(2)  # 20 -> 10 frames
            win.add_caption("Demo")  # adds a TextOverlay over the timeline
            state["frames_after_edit"] = len(win._frames)
            state["overlays"] = len(win._overlays)
            print("after reduce:", len(win._frames), "overlays:", len(win._overlays))
            dlg = ExportDialog(win, win._frames, win._overlays)
            dlg.present()
            dlg.export_to_path(DEST)  # GIF (first preset) on a worker thread
            GLib.timeout_add(3000, check_result)
            return False

        def check_result():
            try:
                state["exported_frames"] = packets(DEST) if DEST.exists() else None
                print("exported file frames:", state["exported_frames"])
                state["ok"] = (
                    state["frames_after_edit"] == 10
                    and state["exported_frames"] == 10
                )
            finally:
                cache.cleanup(); sample.unlink(missing_ok=True); DEST.unlink(missing_ok=True)
                app.quit()
            return False

        GLib.timeout_add(600, edit_and_export)

    app.connect_after("activate", on_activate)
    GLib.timeout_add_seconds(20, app.quit)
    app.run([])

    print("frames_after_edit:", state["frames_after_edit"])
    print("exported_frames:", state["exported_frames"])
    print("RESULT:", "PASS" if state["ok"] else "FAIL")
    raise SystemExit(0 if state["ok"] else 1)


if __name__ == "__main__":
    main()
