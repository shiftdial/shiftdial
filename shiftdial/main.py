"""Entry point: tray icon, single-instance lock, logging, wheel + job queue wiring."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, QPointF, QRectF, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from shiftdial import __version__, paste
from shiftdial.engines.files import locks_report
from shiftdial.hooks import DragHooks
from shiftdial.jobs import JobQueue
from shiftdial.registry import TOOL_BY_ID
from shiftdial.ui import theme
from shiftdial.ui.progress_cards import CardStack
from shiftdial.ui.settings_window import SettingsWindow
from shiftdial.ui.tool_window import ToolWindow
from shiftdial.utils import paths as output_paths
from shiftdial.utils import settings
from shiftdial.utils.paths import data_dir
from shiftdial.wheel import Wheel

log = logging.getLogger("shiftdial")
DISMISS_AFTER_RELEASE_MS = 400  # the OLE drop reaches the wheel shortly *after* the button-up
REPO = "https://github.com/shiftdial/shiftdial"
HOW_TO = ("Start dragging files in Explorer, then press Shift for formats, or Ctrl+Shift for tools like "
          "Remove bg, Get text and Rename. Drop on a wedge.")
ABOUT = (f"Shiftdial {__version__}\n\nConvert files by pressing Shift while you drag them.\n\n"
         "Copyright (c) 2026 ruchitdonga. Free software under the GNU AGPL v3, with no warranty.\n"
         f"Source code: {REPO}\n\nBundles ffmpeg (GPL), PyMuPDF (AGPL), ONNX Runtime (MIT) and the IS-Net "
         "background-removal model (Apache-2.0).")

def make_icon(size: int = 64) -> QIcon:
    """The dial in miniature, drawn in code so there is no asset to ship (build.ps1 renders the .ico)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 64, size / 64)
    p.setPen(QPen(QColor("#3b3a36"), 1.5))
    p.setBrush(QColor("#1c1b19"))
    p.drawEllipse(QRectF(3, 3, 58, 58))
    orange = QColor("#ff5b1f")
    p.setPen(QPen(orange, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    p.drawArc(QRectF(10, 10, 44, 44), 90 * 16, -100 * 16)
    p.setPen(QPen(QColor("#3b3a36"), 1.5))
    p.setBrush(QColor("#2a2926"))
    p.drawEllipse(QPointF(32, 32), 12, 12)
    p.setPen(QPen(orange, 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(32, 32), QPointF(39.5, 26.5))
    p.end()
    return QIcon(pm)


def setup_logging() -> None:
    logs = data_dir() / "logs"
    logs.mkdir(exist_ok=True)
    handler = RotatingFileHandler(logs / "shiftdial.log", maxBytes=1_000_000, backupCount=3,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Shiftdial")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setWindowIcon(make_icon(256))
    prefs = settings.load()
    theme.set_mode(prefs["theme"])
    theme.apply(app)
    output_paths.use_subfolder = prefs["subfolder"]

    def save_prefs() -> None:
        try:
            settings.save(prefs)
        except OSError:  # a settings write must never break a conversion
            log.warning("couldn't save settings", exc_info=True)

    lock = QLockFile(str(data_dir() / "shiftdial.lock"))
    if not lock.tryLock(100):
        return 0
    setup_logging()
    log.info("started")

    queue = JobQueue()
    cards = CardStack(retry=queue.retry)
    wheel = Wheel()
    wheel.grab()  # paint once off-screen: loads fonts/glyphs now, so the first pop-in doesn't stutter
    wheel.usage = prefs["usage"]  # the same dict, so counts saved below reorder the next dial
    queue.job_added.connect(cards.add)
    wheel.released.connect(cards.add)
    tool_windows: set[ToolWindow] = set()

    def on_chosen(paths: list[Path], item: str) -> None:
        prefs["usage"][item] = prefs["usage"].get(item, 0) + 1
        save_prefs()
        if item == "file:locks":
            # later, not inside the drop: a modal box there would stall Explorer's drag
            QTimer.singleShot(0, lambda: QMessageBox.information(None, "In use by", locks_report(paths)))
            return
        tool = TOOL_BY_ID.get(item)
        if not (tool and tool.window):
            wheel.track(queue.submit(paths, item, announce=False))
            return
        try:
            win = ToolWindow(paths, item)
        except Exception as e:  # noqa: BLE001 - e.g. unreadable file; tell the user, keep running
            log.exception("tool window %s", item)
            tray.showMessage("Shiftdial", f"Can't open {tool.label}: {e}", QSystemTrayIcon.MessageIcon.Warning)
            return
        win.applied.connect(queue.submit)
        win.destroyed.connect(lambda: tool_windows.discard(win))
        tool_windows.add(win)
        win.show()
        win.raise_()
        win.activateWindow()

    wheel.chosen.connect(on_chosen)

    def on_drag_event(event: str) -> None:
        if event in ("formats", "tools"):
            wheel.popup(event, activate=False)  # never steal focus from the drag source
        elif event == "dismiss":
            wheel.dismiss()
        elif event == "end":
            QTimer.singleShot(DISMISS_AFTER_RELEASE_MS, wheel, wheel.end_drag)

    hooks = DragHooks()
    hooks.event.connect(on_drag_event)
    hooks.start()

    tray = QSystemTrayIcon(make_icon())
    tray.setToolTip("Shiftdial: drag files from Explorer, then hold Shift (tools: Ctrl+Shift)")
    menu = QMenu()

    def open_last() -> None:
        if queue.last_output_dir:
            os.startfile(queue.last_output_dir)  # noqa: S606

    last = QAction("Open last output folder", menu, triggered=open_last)
    menu.aboutToShow.connect(lambda: last.setEnabled(queue.last_output_dir is not None))
    menu.addAction(last)
    menu.addAction(QAction("Cancel all jobs", menu, triggered=queue.cancel_all))

    def save_clipboard() -> None:
        folder = paste.explorer_folder() or Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation))
        try:
            saved = paste.save_clipboard(folder)
        except OSError as e:
            tray.showMessage("Shiftdial", f"Couldn't save the clipboard: {e}", QSystemTrayIcon.MessageIcon.Warning)
            return
        if saved is None:
            tray.showMessage("Shiftdial", "The clipboard has no picture or text to save.")
            return
        queue.last_output_dir = saved.parent
        tray.showMessage(f"Saved {saved.name}", str(saved.parent))

    menu.addAction(QAction("Save clipboard as file", menu, triggered=save_clipboard))
    menu.addSeparator()
    settings_window: list[SettingsWindow] = []  # at most one; emptied when it closes

    def open_settings() -> None:
        if not settings_window:
            win = SettingsWindow(prefs, save_prefs)
            win.destroyed.connect(settings_window.clear)
            settings_window.append(win)
        win = settings_window[0]
        win.show()
        win.raise_()
        win.activateWindow()

    menu.addAction(QAction("Settings…", menu, triggered=open_settings))
    menu.addSeparator()

    def show_tip() -> None:
        tray.showMessage("How to use Shiftdial", HOW_TO, QSystemTrayIcon.MessageIcon.Information, 12000)

    menu.addAction(QAction("How to use", menu, triggered=show_tip))
    menu.addAction(QAction("Send feedback", menu, triggered=lambda: os.startfile(f"{REPO}/issues/new")))
    menu.addAction(QAction("About Shiftdial", menu, triggered=lambda: QMessageBox.about(None, "About Shiftdial", ABOUT)))
    menu.addAction(QAction("Quit", menu, triggered=app.quit))
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger and show_tip())
    tray.show()
    if not prefs["welcomed"]:  # first run: nobody guesses the Shift gesture on their own
        QTimer.singleShot(1500, show_tip)
        prefs["welcomed"] = True
        save_prefs()

    def on_quit() -> None:
        hooks.stop()
        queue.shutdown()
        log.info("quit")

    app.aboutToQuit.connect(on_quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
