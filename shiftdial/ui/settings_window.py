"""Settings window, opened from the tray."""
from __future__ import annotations

import os
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton

from shiftdial import __version__
from shiftdial.ui import theme
from shiftdial.ui.widgets import Panel
from shiftdial.utils import context_menu, paths, settings, startup
from shiftdial.utils.paths import data_dir


class SettingsWindow(Panel):
    """Each control applies and saves as soon as it changes; there is no OK button to forget."""

    def __init__(self, prefs: dict[str, Any], save: Callable[[], None],
                 set_key: Callable[[str], None] = lambda _: None) -> None:
        super().__init__("Shiftdial · Settings")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.prefs, self.save, self.set_key = prefs, save, set_key
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self.theme = QComboBox()
        for mode in settings.THEMES:
            self.theme.addItem(mode.title(), mode)
        self.theme.setCurrentIndex(settings.THEMES.index(prefs["theme"]))
        self.theme.currentIndexChanged.connect(self._theme)
        form.addRow("Theme", self.theme)

        self.key = QComboBox()
        for name, text in zip(settings.KEYS, ("Shift", "Caps Lock", "Alt")):
            self.key.addItem(f"{text}  (tools: {text} + Ctrl)", name)
        self.key.setCurrentIndex(settings.KEYS.index(prefs["key"]))
        self.key.currentIndexChanged.connect(self._key)
        form.addRow("Dial key", self.key)

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

    def _key(self) -> None:
        self.prefs["key"] = self.key.currentData()
        self.save()
        self.set_key(self.prefs["key"])

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
