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


def test_get_text_with_no_text_fails_and_writes_nothing(tmp_path: Path) -> None:
    src = tmp_path / "blank.png"
    Image.new("RGB", (300, 200), "white").save(src)
    with pytest.raises(ValueError, match="No text found"):
        apply_tool([src], "image:text")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["blank.png"]
