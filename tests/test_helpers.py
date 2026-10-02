import pytest

from vibeloader.errors import ClipTimestampError, friendly
from vibeloader.urls import _host_is_meta, _host_is_youtube
from vibeloader.utils import format_duration, parse_time, windows_safe_video_name
from vibeloader.ytdlp_core import validate_clip_against_duration


@pytest.mark.parametrize(
    "text, expected",
    [
        ("90", 90),
        ("90s", 90),
        ("1m30s", 90),
        ("2m", 120),
        ("1:30", 90),
        ("1:00:05", 3605),
        ("0,5", 0.5),
        ("", None),
        ("   ", None),
        ("abc", None),
        ("1:2:3:4", None),
    ],
)
def test_parse_time(text, expected):
    assert parse_time(text) == expected


@pytest.mark.parametrize(
    "seconds, expected",
    [(0, "0:00"), (59, "0:59"), (61, "1:01"), (3605, "1:00:05"), (None, ""), (-1, ""), ("x", "")],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_windows_safe_video_name():
    assert windows_safe_video_name('a<b>c:"d/e\\f|g?h*') == "abcdefgh"
    assert windows_safe_video_name("  hola   mundo . ") == "hola mundo"
    assert windows_safe_video_name("") == "video"
    assert windows_safe_video_name("???") == "video"
    assert len(windows_safe_video_name("x" * 500, max_len=50)) == 50


def test_friendly_maps_known_errors():
    assert "privado" in friendly("ERROR: Private video. Sign in")
    assert friendly("") == "Algo salió mal."
    assert friendly("linea uno\nlinea dos") == "linea uno"


@pytest.mark.parametrize(
    "host, yt, meta",
    [
        ("www.youtube.com", True, False),
        ("youtu.be", True, False),
        ("music.youtube.com", True, False),
        ("m.facebook.com", False, True),
        ("fb.watch", False, True),
        ("www.instagram.com", False, True),
        ("notyoutube.com", False, False),
        ("evilfacebook.com", False, False),
    ],
)
def test_host_detection(host, yt, meta):
    assert _host_is_youtube(host) is yt
    assert _host_is_meta(host) is meta


def test_validate_clip_ok():
    validate_clip_against_duration("0:10", "0:20", 60)
    validate_clip_against_duration("", "", 60)
    validate_clip_against_duration("10", "", 60)


@pytest.mark.parametrize("start, end", [("0:30", "0:10"), ("0:10", "2:00"), ("60", "")])
def test_validate_clip_rejects(start, end):
    with pytest.raises(ClipTimestampError):
        validate_clip_against_duration(start, end, 60)
