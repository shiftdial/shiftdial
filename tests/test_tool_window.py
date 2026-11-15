"""Tool windows build for every tool that needs one and produce params the engines accept."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QLineEdit  # noqa: E402

from shiftdial.cli import main as cli_main  # noqa: E402
from shiftdial.engines import apply_tool  # noqa: E402
from shiftdial.registry import TOOLS  # noqa: E402
from shiftdial.ui.crop_frame import CropFrame  # noqa: E402
from shiftdial.ui.tool_window import RangeSlider, ToolWindow  # noqa: E402

EXPECTED_KEYS = {
    "image:resize": {"mode", "value", "width", "height", "keep"},
    "image:compress": {"quality"},
    "image:rotate": {"op"},
    "image:crop": {"box"},
    "image:watermark": {"text", "size", "position", "opacity"},
    "video:compress": {"mode", "target_mb", "crf"},
    "video:trim": {"start", "end"},
    "video:speed": {"factor"},
    "video:scale": {"height"},
    "video:frame": {"time"},
    "video:crop": {"box"},
    "audio:trim": {"start", "end"},
    "pdf:rotate": {"angle", "pages"},
    "pdf:delete": {"pages"},
    "any:rename": {"name"},  # one file: no numbering
}
REQUIRED_TEXT = {"image:watermark": "© me", "pdf:delete": "2"}  # no usable default


def test_every_window_tool_is_covered() -> None:
    assert {t.id for t in TOOLS if t.window} == set(EXPECTED_KEYS)
    for tool_id in EXPECTED_KEYS:
        assert hasattr(ToolWindow, "_build_" + tool_id.replace(":", "_")), tool_id


@pytest.mark.parametrize("tool_id", sorted(EXPECTED_KEYS))
def test_window_defaults_run(qtbot, tool_id: str, image: Path, video: Path, audio: Path, pdf: Path) -> None:
    src = {"image": image, "video": video, "audio": audio, "pdf": pdf, "any": image}[tool_id.split(":")[0]]
    win = ToolWindow([src], tool_id)
    qtbot.addWidget(win)
    if tool_id in REQUIRED_TEXT:
        win.findChildren(QLineEdit)[0].setText(REQUIRED_TEXT[tool_id])
    params = win.params()
    assert set(params) == EXPECTED_KEYS[tool_id]
    win.close()  # releases the media player's file handle
    outputs = apply_tool([src], tool_id, params)  # the defaults are valid engine input
    assert outputs and all(o.exists() for o in outputs)


@pytest.mark.parametrize(("tool_id", "preset", "expected"), [
    ("video:compress", "Discord (10 MB)", {"mode": "size", "target_mb": 9.5}),
    ("image:resize", "Instagram (1080 px)", {"mode": "max_side", "value": 1080}),
])
def test_share_presets_fill_the_form(qtbot, tool_id: str, preset: str, expected: dict, image: Path,
                                     video: Path) -> None:
    from PySide6.QtWidgets import QComboBox

    win = ToolWindow([video if tool_id.startswith("video") else image], tool_id)
    qtbot.addWidget(win)
    share = next(cb for cb in win.findChildren(QComboBox) if cb.itemText(0) == "Custom")
    share.setCurrentIndex(share.findText(preset))
    params = win.params()
    win.close()
    assert {k: params[k] for k in expected} == expected


def test_resize_width_and_height_stay_linked(qtbot, image: Path) -> None:
    from PIL import Image as PILImage
    from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox

    w, h = PILImage.open(image).size
    win = ToolWindow([image], "image:resize")
    qtbot.addWidget(win)
    mode = next(cb for cb in win.findChildren(QComboBox) if cb.findData("size") >= 0)
    mode.setCurrentIndex(mode.findData("size"))
    width, height = [sp for sp in win.findChildren(QDoubleSpinBox) if sp.suffix() == " px"][-2:]
    width.setValue(w // 2)
    assert height.value() == round(w // 2 * h / w)  # proportions kept
    win.findChildren(QCheckBox)[0].setChecked(False)
    height.setValue(7)
    assert width.value() == w // 2  # unlinked: changing height leaves width alone
    params = win.params()
    win.close()
    assert (params["mode"], params["width"], params["height"], params["keep"]) == ("size", w // 2, 7, False)


def test_apply_emits_and_validation_blocks(qtbot, image: Path) -> None:
    win = ToolWindow([image], "image:watermark")
    qtbot.addWidget(win)
    with qtbot.assertNotEmitted(win.applied):
        win._apply()  # empty text
    assert "watermark text" in win.error.text()
    win.findChildren(QLineEdit)[0].setText("hi")
    with qtbot.waitSignal(win.applied) as sig:
        win._apply()
    assert sig.args[1] == "image:watermark" and sig.args[2]["text"] == "hi"


def test_crop_aspect_lock(qtbot) -> None:
    frame = CropFrame(QPixmap(64, 40), (640, 400))
    qtbot.addWidget(frame)
    frame.set_aspect(1.0)
    w, h = frame.pixel_size()
    assert abs(w - h) <= 1 and h == 400
    frame.set_aspect(16 / 9)
    w, h = frame.pixel_size()
    assert abs(w / h - 16 / 9) < 0.01


def test_range_slider_handles_cannot_cross(qtbot) -> None:
    s = RangeSlider(1000)
    qtbot.addWidget(s)
    s.set_value(0, 2000)
    assert s.values == [999, 1000]
    s.set_value(1, 0)
    assert s.values == [999, 1000]


def test_cli_tool(image: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["tool", str(image), "--name", "image:crop", "--param", "box=[0,0,0.5,0.5]"]) == 0
    assert Path(capsys.readouterr().out.strip()).exists()
