"""Settings window, opened from the tray."""
from __future__ import annotations

import os
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton

from shiftdial import __version__
from shiftdial.hooks import keys_label, normal
from shiftdial.ui import theme
from shiftdial.ui.widgets import Panel
from shiftdial.utils import context_menu, paths, settings, startup
from shiftdial.utils.paths import data_dir


class KeyButton(QPushButton):
    """Shows a key combo; click it, press any key or combo, let go, and it's recorded. Esc cancels."""

    recorded = Signal(list)

    def __init__(self, keys: list[int]) -> None:
        super().__init__(keys_label(keys))
        self.keys = list(keys)
        self._held: set[int] = set()
        self._combo: list[int] = []
        self._recording = False
        self.clicked.connect(self._start)

    def _start(self) -> None:
        self._recording, self._held, self._combo = True, set(), []
        self.setText("Press a key or combo…")
        self.grabKeyboard()

    def _finish(self, keys: list[int] | None) -> None:
        self._recording = False
        self.releaseKeyboard()
        if keys:
            self.keys = keys
            self.recorded.emit(keys)
        self.setText(keys_label(self.keys))

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if not self._recording:
            return super().keyPressEvent(e)
        vk = normal(e.nativeVirtualKey())
        if vk == 0x1B:  # Esc: keep the old combo
            return self._finish(None)
        if not e.isAutoRepeat() and vk and vk not in self._combo and len(self._combo) < 3:
            self._combo.append(vk)
        self._held.add(vk)
        self.setText(keys_label(self._combo) + " …")

    def keyReleaseEvent(self, e: QKeyEvent) -> None:
        if not self._recording or e.isAutoRepeat():
            return super().keyReleaseEvent(e)
        self._held.discard(normal(e.nativeVirtualKey()))
        if not self._held and self._combo:  # everything let go: that's the combo
            self._finish(self._combo)

    def focusOutEvent(self, e: QFocusEvent) -> None:
        if self._recording:
            self._finish(None)
        super().focusOutEvent(e)


class SettingsWindow(Panel):
    """Each control applies and saves as soon as it changes; there is no OK button to forget."""

    def __init__(self, prefs: dict[str, Any], save: Callable[[], None],
                 set_keys: Callable[[list[int], list[int]], None] = lambda dial, tools: None) -> None:
        super().__init__("Shiftdial · Settings")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.prefs, self.save, self.set_keys = prefs, save, set_keys
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self.theme = QComboBox()
        for mode in settings.THEMES:
            self.theme.addItem(mode.title(), mode)
        self.theme.setCurrentIndex(settings.THEMES.index(prefs["theme"]))
        self.theme.currentIndexChanged.connect(self._theme)
        form.addRow("Theme", self.theme)

        self.dial_key = KeyButton(prefs["dial_keys"])
        self.dial_key.recorded.connect(lambda keys: self._keys("dial_keys", keys))
        form.addRow("Formats key", self.dial_key)
        self.tools_key = KeyButton(prefs["tools_keys"])
        self.tools_key.recorded.connect(lambda keys: self._keys("tools_keys", keys))
        form.addRow("Tools key", self.tools_key)
        hint = QLabel("Click, then press any key or combo while no drag is happening. F8 and F9 always work too.")
        hint.setProperty("role", "sub")
        hint.setWordWrap(True)
        form.addRow("", hint)

        self.notify = QCheckBox("Notify me when a long job finishes")
        self.notify.setChecked(prefs["notify"])
        self.notify.toggled.connect(self._notify)
        form.addRow("Alerts", self.notify)

        self.menu = QCheckBox("Add Shiftdial to the right-click menu")
        self.menu.setEnabled(context_menu.available())
        self.menu.setToolTip("Under “Show more options” on Windows 11" if context_menu.available() else
                             "Not in the Microsoft Store version" if startup.packaged() else
                             "Only in the built Shiftdial.exe")
        self.menu.setChecked(context_menu.available() and context_menu.is_enabled())
        self.menu.toggled.connect(self._menu)
        form.addRow("Explorer", self.menu)

        self.startup = QCheckBox("Start Shiftdial when you sign in")
        self.startup.setEnabled(startup.command() is not None)
        if not self.startup.isEnabled():
            self.startup.setToolTip("Only in the built Shiftdial.exe")
        self.startup.setChecked(startup.is_enabled())
        self.startup.toggled.connect(self._startup)
        form.addRow("Windows", self.startup)

        self.subfolder = QCheckBox(f"Save results into a '{paths.SUBFOLDER}' folder")
        self.subfolder.setChecked(prefs["subfolder"])
        self.subfolder.toggled.connect(self._subfolder)
        form.addRow("Output", self.subfolder)

        reset = QPushButton("Reset")
        reset.clicked.connect(self._reset_order)
        form.addRow("Dial order", self._row(reset, "Most-used formats move to the top. Reset puts them back."))

        logs = QPushButton("Open")
        logs.clicked.connect(lambda: os.startfile(data_dir() / "logs"))  # noqa: S606
        form.addRow("Logs", self._row(logs, "Error details, if a conversion fails."))
        self.body.addLayout(form)

        self.note = QLabel(f"Shiftdial {__version__}")
        self.note.setProperty("role", "sub")
        self.body.addWidget(self.note)
        self.setMinimumWidth(460)

    @staticmethod
    def _row(button: QPushButton, text: str) -> QHBoxLayout:
        hint = QLabel(text)
        hint.setProperty("role", "sub")
        hint.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(button)
        row.addWidget(hint, 1)
        return row

    def _theme(self) -> None:
        self.prefs["theme"] = self.theme.currentData()
        self.save()
        theme.set_mode(self.prefs["theme"])

    def _keys(self, which: str, keys: list[int]) -> None:
        other = self.prefs["tools_keys" if which == "dial_keys" else "dial_keys"]
        button = self.dial_key if which == "dial_keys" else self.tools_key
        if not settings.valid_keys(keys) or set(keys) == set(other):
            self.note.setText("That combo can't be used" if not settings.valid_keys(keys) else
                              "Formats and tools need different keys.")
            button.keys = list(self.prefs[which])
            button.setText(keys_label(button.keys))
            return
        self.prefs[which] = keys
        self.save()
        self.set_keys(self.prefs["dial_keys"], self.prefs["tools_keys"])
        self.note.setText(f"Formats: {keys_label(self.prefs['dial_keys'])}  ·  "
                          f"Tools: {keys_label(self.prefs['tools_keys'])}")

    def _notify(self, on: bool) -> None:
        self.prefs["notify"] = on
        self.save()

    def _menu(self, on: bool) -> None:
        try:
            context_menu.set_enabled(on)
            self.note.setText("Right-click a file › Show more options › Convert with Shiftdial." if on else
                              "Removed from the right-click menu.")
        except (OSError, RuntimeError) as e:
            self.note.setText(f"Couldn't change the right-click menu: {e}")

    def _subfolder(self, on: bool) -> None:
        self.prefs["subfolder"] = paths.use_subfolder = on
        self.save()

    def _reset_order(self) -> None:
        self.prefs["usage"].clear()  # the wheel shares this dict, so the next dial is back to default order
        self.save()
        self.note.setText("Dial order reset.")

    def _startup(self, on: bool) -> None:
        try:
            startup.set_enabled(on)
        except startup.NeedsSettings:
            self.note.setText("You turned Shiftdial off in Windows' Startup apps; switch it back on there.")
            os.startfile("ms-settings:startupapps")  # noqa: S606
        except (OSError, RuntimeError) as e:
            self.note.setText(f"Couldn't change startup: {e}")
        self.startup.blockSignals(True)  # show what Windows actually has, without re-triggering
        self.startup.setChecked(startup.is_enabled())
        self.startup.blockSignals(False)
