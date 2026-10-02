import json
import os
import sys

from vibeloader import updater


def test_parse_version_numeric_order():
    assert updater.parse_version("2026.08.19") == (2026, 8, 19)
    assert updater.parse_version("2026.8.19.1") > updater.parse_version("2026.08.19")
    assert updater.parse_version("2026.10.1") > updater.parse_version("2026.9.30")
    assert updater.parse_version("") == (0,)


def test_ejs_requirement():
    info = {"requires_dist": ["brotli; extra == 'default'", "yt-dlp-ejs==0.8.0; extra == 'default'"]}
    assert updater._ejs_requirement(info) == "0.8.0"
    assert updater._ejs_requirement({"requires_dist": None}) is None


def test_pick_ffmpeg_asset_prefers_newest_stable():
    assets = [
        {"name": "ffmpeg-master-latest-win64-gpl.zip"},
        {"name": "ffmpeg-n8.1-latest-win64-gpl-8.1.zip"},
        {"name": "ffmpeg-n9.0-latest-win64-gpl-9.0.zip"},
        {"name": "ffmpeg-n9.0-latest-win64-gpl-shared-9.0.zip"},
        {"name": "ffmpeg-n9.0-latest-linux64-gpl-9.0.tar.xz"},
    ]
    assert updater.pick_ffmpeg_asset(assets)["name"] == "ffmpeg-n9.0-latest-win64-gpl-9.0.zip"
    assert updater.pick_ffmpeg_asset(assets[:1])["name"] == "ffmpeg-master-latest-win64-gpl.zip"


def _make_overlay(tmp_path, version):
    base = tmp_path / "ytdlp_lib"
    (base / "yt_dlp").mkdir(parents=True)
    (base / "VIBELOADER_OVERLAY.json").write_text(json.dumps({"yt_dlp": version}))
    return str(base)


def test_activate_overlay_only_when_newer_and_frozen(tmp_path, monkeypatch):
    base = _make_overlay(tmp_path, "2026.9.1")
    monkeypatch.setattr(updater, "overlay_dir", lambda: base)
    monkeypatch.setattr(sys, "path", list(sys.path))

    monkeypatch.setattr(updater, "is_frozen", lambda: False)
    assert updater.activate_overlay() is None  # en desarrollo manda pip

    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setattr(updater, "embedded_ytdlp_version", lambda: "2026.10.1")
    assert updater.activate_overlay() is None  # el .exe trae una más nueva
    assert base not in sys.path

    monkeypatch.setattr(updater, "embedded_ytdlp_version", lambda: "2026.8.19")
    assert updater.activate_overlay() == "2026.9.1"
    assert sys.path[0] == base


def test_activate_overlay_ignores_incomplete(tmp_path, monkeypatch):
    base = tmp_path / "ytdlp_lib"
    base.mkdir()
    (base / "VIBELOADER_OVERLAY.json").write_text(json.dumps({"yt_dlp": "2099.1.1"}))
    monkeypatch.setattr(updater, "overlay_dir", lambda: str(base))
    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    assert updater.activate_overlay() is None  # falta la carpeta yt_dlp
    assert os.path.isdir(base)
