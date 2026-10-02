import os
import subprocess
import sys

import pytest

from vibeloader.config import ALL_PRESETS, PRESET_LABELS, SIMPLE_EXTRA_PRESETS, preset_label
from vibeloader.errors import (
    ACTION_COOKIES,
    ACTION_FFMPEG,
    ACTION_FOLDER,
    ACTION_RETRY,
    ACTION_UPDATE,
    ACTION_WAIT,
    explain,
)
from vibeloader.jobs import JobRunner, ProgressInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_core_does_not_import_qt():
    code = "import sys, vibeloader.jobs; print('PySide6' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_runner_reports_errors_through_callbacks(tmp_path):
    events = []
    runner = JobRunner(
        "https://example.com/v",
        str(tmp_path),
        "preset inexistente",
        "",
        "",
        on_error=lambda m: events.append(("error", m)),
        on_finished=lambda: events.append(("finished",)),
        on_progress=lambda info: events.append(("progress", info.pct, info.phase)),
    )
    runner.run()
    assert events[0] == ("progress", 0, "preparando")
    assert events[-2][0] == "error" and "Preset no reconocido" in events[-2][1]
    assert events[-1] == ("finished",)


def test_progress_info_defaults():
    info = ProgressInfo(10, "Descargando 10%")
    assert info.speed is None and info.eta is None


@pytest.mark.parametrize(
    "raw, action",
    [
        ("ERROR: Sign in to confirm your age", ACTION_COOKIES),
        ("Sign in to confirm you're not a bot", ACTION_COOKIES),
        ("HTTP Error 403: Forbidden", ACTION_UPDATE),
        ("ERROR: Unable to extract uploader id", ACTION_UPDATE),
        ("HTTP Error 429: Too Many Requests", ACTION_WAIT),
        ("ffmpeg not found", ACTION_FFMPEG),
        ("[WinError 5] Acceso denegado", ACTION_FOLDER),
        ("algo totalmente nuevo", ACTION_RETRY),
        ("ERROR: Private video", None),
        ("ERROR: [youtube] abc: This video is unavailable", None),
    ],
)
def test_errors_come_with_an_action(raw, action):
    text, got = explain(raw)
    assert got == action
    assert "yt-dlp" not in text and "modo avanzado" not in text.lower()


def test_every_preset_has_a_plain_label():
    for p in ALL_PRESETS:
        assert p in PRESET_LABELS
        assert not preset_label(p).startswith("Modo")
    assert set(SIMPLE_EXTRA_PRESETS) <= set(ALL_PRESETS)
    assert preset_label("desconocido") == "desconocido"


def test_brand_small_cuts_are_centered_and_pixel_aligned():
    from vibeloader.ui.brand import MASTER_GEOM, SMALL_CUTS, svg_path_d

    for size, g in SMALL_CUTS.items():
        assert g["x0"] + g["x1"] == size  # vértice centrado en la placa
        assert float(g["top"]).is_integer()
        for a, b in g.get("slits", ()):
            assert float(a).is_integer() and float(b).is_integer()
            assert g["x0"] < a < b < g["x1"]
    d = svg_path_d(MASTER_GEOM)
    assert d.startswith("M") and d.endswith("Z")


def test_simple_view_formats():
    from vibeloader.ui.simple_view import format_eta, short_folder

    assert format_eta(None) == ""
    assert format_eta(13) == "quedan 15 s"
    assert format_eta(2) == "quedan 5 s"
    assert format_eta(130) == "quedan 2 min"
    assert format_eta(70) == "queda 1 min"
    assert short_folder(r"C:\Users\Ana\Videos\VibeLoader\HD") == "VibeLoader › HD"


def test_advanced_view_formats():
    from vibeloader.ui.advanced_view import format_clock, format_speed

    assert format_speed(None) == ""
    assert format_speed(3_400_000) == "3,4 MB/s"
    assert format_clock(75) == "1:15"
    assert format_clock(3725) == "1:02:05"


def test_colorref_is_bgr():
    from vibeloader.ui.win_integration import _colorref

    assert _colorref("#0F0D16") == 0x160D0F


def test_slim_dist_removes_unused_qt(tmp_path):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    try:
        from slim_dist import slim
    finally:
        sys.path.pop(0)
    qt = tmp_path / "_internal" / "PySide6"
    (qt / "translations").mkdir(parents=True)
    (qt / "translations" / "qt_es.qm").write_bytes(b"x" * 10)
    (qt / "opengl32sw.dll").write_bytes(b"x" * 100)
    (qt / "Qt6Widgets.dll").write_bytes(b"x" * 5)
    assert slim(str(tmp_path)) == 110
    assert (qt / "Qt6Widgets.dll").exists()
    assert not (qt / "opengl32sw.dll").exists() and not (qt / "translations").exists()
