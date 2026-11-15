"""Favourite ordering, the Converted-folder option and Get text (Windows OCR)."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from shiftdial.engines import apply_tool, convert
from shiftdial.registry import by_use, tools_for
from shiftdial.utils import paths
from shiftdial.utils.paths import Output, commit_dir


def test_by_use_puts_favourites_first_and_keeps_ties_in_order() -> None:
    items = ["png", "jpg", "webp", "avif"]
    assert by_use(items, {}) == items
    assert by_use(items, {"webp": 5, "avif": 2}) == ["webp", "avif", "png", "jpg"]
    assert by_use(items, {"gif": 9}) == items  # counts for items not on this dial are ignored


@pytest.fixture
def subfolder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "use_subfolder", True)


def test_outputs_go_to_converted_folder(tmp_path: Path, subfolder: None) -> None:
    src = tmp_path / "photo.png"
    Image.new("RGB", (8, 8), "red").save(src)
    [out] = convert([src], "jpg")
    assert out == tmp_path / "Converted" / "photo.jpg" and out.exists()
    [again] = convert([out], "png")  # converting a file already in Converted doesn't nest another level
    assert again.parent == tmp_path / "Converted"

    done = tmp_path / "work"
    done.mkdir()
    assert commit_dir(done, tmp_path, "pages") == tmp_path / "Converted" / "pages"


def test_subfolder_off_writes_beside_the_source(tmp_path: Path) -> None:
    assert not paths.use_subfolder
    assert Output.next_to(tmp_path / "a.png", "jpg").final == tmp_path / "a.jpg"
    assert not (tmp_path / "Converted").exists()


def test_get_text_reads_an_image(tmp_path: Path) -> None:
    assert "image:text" in tools_for([Path("a.png")])
    src = tmp_path / "note.png"
    im = Image.new("RGB", (900, 220), "white")
    font = ImageFont.truetype("arial.ttf", 48)
    ImageDraw.Draw(im).text((30, 30), "Shiftdial reads text", fill="black", font=font)
    ImageDraw.Draw(im).text((30, 120), "on two lines", fill="black", font=font)
    im.save(src)
    [out] = apply_tool([src], "image:text")
    assert out == tmp_path / "note.txt"
    assert out.read_text(encoding="utf-8").splitlines() == ["Shiftdial reads text", "on two lines"]


def test_rename_numbers_in_name_order_and_never_overwrites(tmp_path: Path) -> None:
    for n in ("b.jpg", "a.jpg", "c.png", "Trip 1.jpg"):
        (tmp_path / n).write_text(n)
    srcs = [tmp_path / n for n in ("b.jpg", "a.jpg", "c.png")]
    out = apply_tool(srcs, "any:rename", {"name": "Trip"})
    # 'Trip 1.jpg' already existed (not part of the batch), so a.jpg gets a suffix rather than replacing it
    assert [p.name for p in out] == ["Trip 1 (1).jpg", "Trip 2.jpg", "Trip 3.png"]
    assert (tmp_path / "Trip 1.jpg").read_text() == "Trip 1.jpg"
    assert (tmp_path / "Trip 1 (1).jpg").read_text() == "a.jpg"
    [same] = apply_tool([tmp_path / "Trip 3.png"], "any:rename", {"name": "trip 3"})  # case-only change
    assert same.name == "trip 3.png" and same.read_text() == "c.png"
    many = [tmp_path / f"{i}.txt" for i in range(10)]
    for f in many:
        f.write_text("x")
    assert apply_tool(many, "any:rename", {"name": "Doc"})[0].name == "Doc 01.txt"  # 10 files: padded to 2
    for bad in ("", "a/b", "x?", "dot."):
        with pytest.raises(ValueError):
            apply_tool([same], "any:rename", {"name": bad})


def test_hash_matches_hashlib_and_is_copied(tmp_path: Path) -> None:
    import hashlib

    from shiftdial.engines import JobContext

    src = tmp_path / "setup.iso"
    src.write_bytes(b"x" * 3_000_000)
    ctx = JobContext()
    [out] = apply_tool([src], "file:hash", ctx=ctx)
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    assert out.name == "setup.iso.sha256" and out.read_text() == f"{digest} *setup.iso\n"
    assert ctx.clipboard == digest


def test_any_file_tools_fit_the_right_selections(tmp_path: Path) -> None:
    (tmp_path / "d").mkdir()
    assert {"any:rename", "file:hash", "file:locks"} <= set(tools_for([Path("x.exe"), Path("y.mp4")]))
    assert "file:hash" not in tools_for([tmp_path / "d", Path("y.mp4")])  # a folder in the mix


def test_locked_by_finds_this_process(tmp_path: Path) -> None:
    import os

    from shiftdial.engines.files import locked_by

    f = tmp_path / "busy.txt"
    f.write_text("x")
    assert locked_by([f]) == []
    with f.open("rb"):
        assert os.getpid() in [pid for _, pid in locked_by([f])]


def test_save_clipboard_image_text_and_nothing(qtbot, tmp_path: Path) -> None:
    from PySide6.QtGui import QGuiApplication, QImage

    from shiftdial.paste import save_clipboard

    cb = QGuiApplication.clipboard()
    img = QImage(20, 10, QImage.Format.Format_RGB32)
    img.fill(0xFF5B1F)
    cb.setImage(img)
    png = save_clipboard(tmp_path)
    assert png.suffix == ".png" and Image.open(png).size == (20, 10)
    cb.setText("hello")
    txt = save_clipboard(tmp_path)
    assert txt.read_text(encoding="utf-8") == "hello"
    cb.clear()
    assert save_clipboard(tmp_path) is None


def test_remove_background_cuts_out_the_subject(tmp_path: Path) -> None:
    from shiftdial.engines.image import model_path

    if not model_path().exists():
        pytest.skip("model not downloaded; build.ps1 fetches it")
    src = tmp_path / "ball.jpg"
    im = Image.new("RGB", (800, 600), (235, 235, 230))
    ImageDraw.Draw(im).ellipse((250, 150, 550, 450), fill=(200, 40, 40))
    im.save(src)
    [out] = apply_tool([src], "image:nobg")
    assert out.name == "ball cutout.png"
    cut = Image.open(out)
    assert cut.mode == "RGBA" and cut.size == (800, 600)
    assert cut.getpixel((400, 300))[3] > 200  # the ball stays
    assert cut.getpixel((20, 20))[3] < 30  # the background goes


def test_settings_window_applies_and_saves(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    from shiftdial.ui import settings_window, theme
    from shiftdial.utils import settings

    modes: list[str] = []
    monkeypatch.setattr(theme, "set_mode", modes.append)
    monkeypatch.setattr(paths, "use_subfolder", False)
    prefs = {**settings.DEFAULTS, "usage": {"webp": 4}}
    saves: list[int] = []
    win = settings_window.SettingsWindow(prefs, lambda: saves.append(1))
    qtbot.addWidget(win)

    win.theme.setCurrentIndex(settings.THEMES.index("dark"))
    assert prefs["theme"] == "dark" and modes == ["dark"]
    win.subfolder.setChecked(True)
    assert prefs["subfolder"] and paths.use_subfolder
    win._reset_order()
    assert prefs["usage"] == {}
    assert len(saves) == 3
    assert not win.startup.isEnabled()  # running from source: Start with Windows needs the built exe


def test_resize_to_width_and_height(tmp_path: Path) -> None:
    src = tmp_path / "wide.png"
    Image.new("RGB", (400, 200), "blue").save(src)
    [fit] = apply_tool([src], "image:resize", {"mode": "size", "width": 100, "height": 100, "keep": True})
    assert Image.open(fit).size == (100, 50)  # fits inside 100×100 without distortion
    [exact] = apply_tool([src], "image:resize", {"mode": "size", "width": 100, "height": 100, "keep": False})
    assert Image.open(exact).size == (100, 100)  # stretched to exactly the size asked
    with pytest.raises(ValueError):
        apply_tool([src], "image:resize", {"mode": "size", "width": 0, "height": 100})


def test_pdf_lock_and_unlock(tmp_path: Path) -> None:
    import pymupdf

    from shiftdial.engines import PasswordRequired

    src = tmp_path / "report.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secret plan")
    doc.save(src)
    [locked] = apply_tool([src], "pdf:lock", {"password": "hunter22"})
    assert locked.name == "report locked.pdf" and pymupdf.open(locked).needs_pass
    with pytest.raises(PasswordRequired):
        apply_tool([locked], "pdf:unlock")
    with pytest.raises(PasswordRequired, match="Wrong"):
        apply_tool([locked], "pdf:unlock", {"password": "nope"})
    [opened] = apply_tool([locked], "pdf:unlock", {"password": "hunter22"})
    assert opened.name == "report (1).pdf"  # 'locked' dropped; the original report.pdf is still there
    assert "secret plan" in pymupdf.open(opened)[0].get_text()
    with pytest.raises(ValueError, match="isn't password protected"):
        apply_tool([src], "pdf:unlock", {"password": "x"})


def test_lock7z_hides_names_and_contents(tmp_path: Path) -> None:
    import py7zr

    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "a.txt").write_text("top secret")
    [z] = apply_tool([tmp_path / "plans"], "any:lock7z", {"password": "hunter22"})
    assert z.name == "plans.7z"
    with pytest.raises(py7zr.exceptions.PasswordRequired):
        py7zr.SevenZipFile(z).getnames()  # even the file list needs the password
    with py7zr.SevenZipFile(z, password="hunter22") as s:
        assert s.getnames() == ["plans", "plans/a.txt"] or "plans/a.txt" in s.getnames()


def test_same_report(tmp_path: Path) -> None:
    from shiftdial.engines.files import same_report

    a, b, c, d = (tmp_path / n for n in ("a.bin", "b.bin", "c.bin", "d.bin"))
    a.write_bytes(b"x" * 10)
    b.write_bytes(b"x" * 10)
    c.write_bytes(b"y" * 10)  # same size, different bytes
    d.write_bytes(b"x" * 11)
    assert same_report([a, b]) == "a.bin and b.bin are identical."
    assert same_report([a, c]) == "a.bin and c.bin are different."
    assert same_report([a, b, a]) == "All 3 files are identical."
    assert same_report([a, c, d]) == "All 3 files are different."
    assert "a.bin, b.bin" in same_report([a, b, c, d])


def test_dial_request_from_the_right_click_menu() -> None:
    from shiftdial.main import dial_request

    assert dial_request(["--dial", "tools", "C:\\a.png", "C:\\b.png"]) == ("tools", ["C:\\a.png", "C:\\b.png"])
    assert dial_request(["--dial", "evil", "C:\\a.png"]) is None
    assert dial_request([]) is None


def test_context_menu_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    import winreg

    from shiftdial.utils import context_menu, startup

    root = r"Software\ShiftdialTest\Classes"
    monkeypatch.setattr(startup, "command", lambda: r'"C:\Apps\Shiftdial\Shiftdial.exe"')
    try:
        context_menu.set_enabled(True, root)
        assert context_menu.is_enabled(root)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\*\shell\Shiftdial.Convert\command") as k:
            assert winreg.QueryValue(k, None) == r'"C:\Apps\Shiftdial\Shiftdial.exe" --dial formats "%1"'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{root}\Directory\shell\Shiftdial.Tools") as k:
            assert winreg.QueryValueEx(k, "MUIVerb")[0] == "Shiftdial tools"
        context_menu.set_enabled(False, root)
        assert not context_menu.is_enabled(root)
    finally:
        context_menu.set_enabled(False, root)
        for sub in (rf"{root}\*\shell", rf"{root}\*", rf"{root}\Directory\shell", rf"{root}\Directory", root,
                    r"Software\ShiftdialTest"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except OSError:
                pass


def test_separate_keys_for_each_dial() -> None:
    from shiftdial.hooks import VK_CAPITAL, VK_LCONTROL, VK_LSHIFT, WM_KEYDOWN, WM_LBUTTONDOWN, WM_MOUSEMOVE, \
        DragDetector, keys_label

    events: list[str] = []
    det = DragDetector(events.append, lambda x, y: True)
    det.dial_keys, det.tools_keys = frozenset({VK_CAPITAL}), frozenset({0x11, 0x51})  # Caps Lock; Ctrl + Q
    det.mouse(WM_LBUTTONDOWN, 0, 0)
    det.mouse(WM_MOUSEMOVE, 50, 0)
    det.key(WM_KEYDOWN, VK_LSHIFT)
    assert events == []  # Shift no longer opens anything: it's back to just 'move'
    det.key(WM_KEYDOWN, VK_CAPITAL)
    assert events == ["formats"]
    det.key(WM_KEYDOWN, VK_LCONTROL)  # left Ctrl counts as Ctrl
    det.key(WM_KEYDOWN, 0x51)
    assert events[-1] == "tools"
    assert keys_label([0x10, 0x11]) == "Ctrl + Shift"
    assert keys_label([0x51, 0x11]) == "Ctrl + Q"
    assert keys_label([VK_CAPITAL]) == "Caps Lock"


def test_settings_window_records_keys_and_notify(qtbot) -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    from shiftdial.ui.settings_window import SettingsWindow
    from shiftdial.utils import settings

    applied: list[tuple] = []
    prefs = settings.load(Path("missing-settings.json"))
    win = SettingsWindow(prefs, lambda: None, lambda d, t: applied.append((d, t)))
    qtbot.addWidget(win)

    def key(kind: QEvent.Type, qt_key: Qt.Key, vk: int) -> None:
        QApplication.sendEvent(win.tools_key, QKeyEvent(kind, qt_key, Qt.KeyboardModifier.NoModifier, 0, vk, 0))

    win.tools_key.click()  # start recording, then press Ctrl + Q and let go
    key(QEvent.Type.KeyPress, Qt.Key.Key_Control, 0xA2)
    key(QEvent.Type.KeyPress, Qt.Key.Key_Q, 0x51)
    key(QEvent.Type.KeyRelease, Qt.Key.Key_Q, 0x51)
    key(QEvent.Type.KeyRelease, Qt.Key.Key_Control, 0xA2)
    assert prefs["tools_keys"] == [0x11, 0x51] and applied == [([0x10], [0x11, 0x51])]
    assert win.tools_key.text() == "Ctrl + Q"

    win._keys("dial_keys", [0x11, 0x51])  # same as tools: refused, nothing changes
    assert prefs["dial_keys"] == [0x10] and "different" in win.note.text()

    win.notify.setChecked(False)
    assert prefs["notify"] is False
    assert not win.menu.isEnabled()  # running from source: needs the built exe


def test_right_click_dial_picks_by_clicking(qtbot, tmp_path: Path) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from shiftdial.wheel import R_IN, R_OUT, Wheel

    src = tmp_path / "a.png"
    Image.new("RGB", (8, 8)).save(src)
    wheel = Wheel()
    qtbot.addWidget(wheel)
    wheel.pick("formats", [src])
    centre = QPoint(wheel.width() // 2, wheel.height() // 2)
    top_wedge = centre - QPoint(0, (R_IN + R_OUT) // 2)  # wedge 0 sits at 12 o'clock
    with qtbot.waitSignal(wheel.chosen) as sig:
        QTest.mouseClick(wheel, Qt.MouseButton.LeftButton, pos=top_wedge)
    assert sig.args == [[src], wheel.items[0]] or sig.args[0] == [src]
    wheel.pick("formats", [src])
    with qtbot.assertNotEmitted(wheel.chosen):
        QTest.mouseClick(wheel, Qt.MouseButton.LeftButton, pos=centre)  # the hub: just closes
    assert not wheel._picking


def test_get_text_with_no_text_fails_and_writes_nothing(tmp_path: Path) -> None:
    src = tmp_path / "blank.png"
    Image.new("RGB", (300, 200), "white").save(src)
    with pytest.raises(ValueError, match="No text found"):
        apply_tool([src], "image:text")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["blank.png"]
