from PySide6.QtCore import QSettings

from vibeloader.ffmpeg_core import FFMPEG_PROFILE_WHATSAPP, ConversionPlan, MediaInfo, build_convert_cmd
from vibeloader.history import add_history, clear_history, load_history
from vibeloader.ytdlp_core import pick_subtitle_codes


def test_pick_subtitle_codes_priorities():
    manual = {"es-419": [], "en": []}
    auto = {"es": [], "en-orig": [], "fr": []}
    assert pick_subtitle_codes(manual, auto, ["es", "en"]) == {"es": ("es-419", False), "en": ("en", False)}
    assert pick_subtitle_codes({}, {"en-orig": [], "en": []}, ["en"]) == {"en": ("en-orig", True)}
    assert pick_subtitle_codes({}, {"es": []}, ["es"]) == {"es": ("es", True)}  # traducción automática
    assert pick_subtitle_codes(None, None, ["es"]) == {}


def test_history_roundtrip(tmp_path):
    s = QSettings(str(tmp_path / "h.ini"), QSettings.Format.IniFormat)
    assert load_history(s) == []
    add_history(s, title="Uno", path="C:/a.mp4", preset="X", url="u1")
    add_history(s, title="Dos «ñ»", path="C:/b.mp4", preset="Y", url="u2")
    h = load_history(s)
    assert [e["title"] for e in h] == ["Dos «ñ»", "Uno"]
    clear_history(s)
    assert load_history(s) == []


def test_build_cmd_with_subtitles_and_clip():
    info = MediaInfo(duration=60, has_video=True, width=1280, height=720, fps=30, vcodec="h264",
                     has_audio=True, acodec="aac", asample_rate=44100, achannels=2)
    plan = ConversionPlan(video_copy=False, audio_copy=True, dims=None, fps_str=None)
    cmd = build_convert_cmd(
        "in.mp4", "out.mp4", FFMPEG_PROFILE_WHATSAPP, plan, info, encoder="libx264",
        clip=(10.0, 20.0), subtitles=[("a.es.srt", "es"), ("a.en.srt", "en")],
    )
    # -ss antes de cada entrada; -t después de todas (opción de salida)
    inputs = [i for i, x in enumerate(cmd) if x == "-i"]
    assert len(inputs) == 3 and all(cmd[i - 2] == "-ss" for i in inputs)
    assert cmd.index("-t") > inputs[-1]
    assert ["-map", "1:0", "-map", "2:0"] == cmd[cmd.index("1:0") - 1: cmd.index("2:0") + 1]
    assert "-sn" not in cmd and cmd[cmd.index("-c:s") + 1] == "mov_text"
    assert "language=spa" in cmd and "language=eng" in cmd
