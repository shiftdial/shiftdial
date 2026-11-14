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


def test_get_text_with_no_text_fails_and_writes_nothing(tmp_path: Path) -> None:
    src = tmp_path / "blank.png"
    Image.new("RGB", (300, 200), "white").save(src)
    with pytest.raises(ValueError, match="No text found"):
        apply_tool([src], "image:text")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["blank.png"]
