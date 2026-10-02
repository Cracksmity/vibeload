import pytest

from vibeloader.errors import TargetSizeTooSmallError
from vibeloader.ffmpeg_core import (
    FFMPEG_PROFILE_CAR,
    FFMPEG_PROFILE_CURSOS,
    FFMPEG_PROFILE_WHATSAPP,
    ConversionPlan,
    MediaInfo,
    build_convert_cmd,
    fit_dimensions,
    parse_ffprobe_json,
    plan_conversion,
    target_bitrates,
    video_encoder_args,
)


@pytest.mark.parametrize(
    "w, h, expected",
    [
        (1920, 1080, (1280, 720)),  # horizontal
        (1080, 1920, (720, 1280)),  # vertical (antes quedaba 405×720)
        (1080, 1080, (720, 720)),  # cuadrado: respeta el tope de píxeles de L3.1
        (1440, 1080, (960, 720)),  # 4:3
        (640, 360, (640, 360)),  # más chico: no se agranda
        (853, 480, (852, 480)),  # impar → par
        (0, 0, None),
    ],
)
def test_fit_dimensions(w, h, expected):
    assert fit_dimensions(w, h, 1280, 720) == expected


def _yt720(**kw):
    base = dict(
        duration=60.0, has_video=True, width=1280, height=720, fps=30.0, fps_str="30/1",
        vcodec="h264", vprofile="Main", vlevel=31, pix_fmt="yuv420p",
        has_audio=True, acodec="aac", aprofile="LC", achannels=2, asample_rate=44100,
    )
    base.update(kw)
    return MediaInfo(**base)


def test_whatsapp_copies_compatible_youtube_720p():
    plan = plan_conversion(FFMPEG_PROFILE_WHATSAPP, _yt720())
    assert plan.video_copy and plan.audio_copy and plan.dims is None and plan.fps_str is None


def test_car_reencodes_main_profile_but_copies_nothing_wrong():
    plan = plan_conversion(FFMPEG_PROFILE_CAR, _yt720())
    assert not plan.video_copy  # Baseline obligatorio
    assert plan.audio_copy  # AAC LC 44.1 kHz ya es lo que pide el perfil


def test_car_resamples_48k_audio():
    assert not plan_conversion(FFMPEG_PROFILE_CAR, _yt720(asample_rate=48000)).audio_copy


def test_fps_only_capped_when_above():
    assert plan_conversion(FFMPEG_PROFILE_WHATSAPP, _yt720(fps=24.0, fps_str="24/1")).fps_str is None
    plan = plan_conversion(FFMPEG_PROFILE_WHATSAPP, _yt720(fps=60.0, fps_str="60/1"))
    assert plan.fps_str == "30" and not plan.video_copy


def test_clip_forces_video_reencode():
    assert not plan_conversion(FFMPEG_PROFILE_WHATSAPP, _yt720(), clip=(5, 10)).video_copy


def test_hevc_profile_never_copies_h264():
    assert not plan_conversion(FFMPEG_PROFILE_CURSOS, _yt720()).video_copy


def test_target_bitrates():
    v, a, box = target_bitrates(25, 120)  # 25 MB en 2 min
    assert a == 128 and 1500 < v < 1700 and box == (1280, 720)
    v, a, box = target_bitrates(16, 600)  # 16 MB en 10 min
    assert a == 64 and box == (640, 360)
    with pytest.raises(TargetSizeTooSmallError):
        target_bitrates(5, 3600)


def test_encoder_args():
    a = video_encoder_args("libx264", FFMPEG_PROFILE_CAR)
    assert a[a.index("-profile:v") + 1] == "baseline" and "-crf" in a
    a = video_encoder_args("h264_amf", FFMPEG_PROFILE_CAR)
    assert a[a.index("-profile:v") + 1] == "constrained_baseline" and a[a.index("-bf") + 1] == "0"
    assert a[a.index("-pix_fmt") + 1] == "nv12"
    a = video_encoder_args("libx265", FFMPEG_PROFILE_CURSOS)
    assert "hvc1" in a and "-crf" in a
    a = video_encoder_args("libx264", FFMPEG_PROFILE_WHATSAPP, bitrate_k=900)
    assert "-b:v" in a and "-crf" not in a


def test_build_cmd_clip_and_copy():
    info = _yt720()
    plan = ConversionPlan(video_copy=False, audio_copy=True, dims=(720, 1280), fps_str="30")
    cmd = build_convert_cmd("in.mp4", "out.mp4", FFMPEG_PROFILE_WHATSAPP, plan, info, encoder="libx264", clip=(10.0, 25.0))
    assert cmd[cmd.index("-ss") + 1] == "10.000" and cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-t") + 1] == "15.000"
    assert "scale=720:1280,fps=30,setsar=1" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    assert cmd[-1] == "out.mp4" and "+faststart" in cmd


def test_build_cmd_pass1_has_no_output_file():
    plan = ConversionPlan(False, False, None, None)
    cmd = build_convert_cmd("in.mp4", "out.mp4", FFMPEG_PROFILE_WHATSAPP, plan, _yt720(), encoder="libx264", bitrate_k=800, pass_no=1, passlog="x")
    assert cmd[-3:] == ["-f", "null", "-"] and "out.mp4" not in cmd


def test_parse_ffprobe_json_skips_cover_art():
    data = {
        "format": {"duration": "12.5"},
        "streams": [
            {"codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}},
            {"codec_type": "audio", "codec_name": "mp3", "channels": 2, "sample_rate": "44100"},
        ],
    }
    info = parse_ffprobe_json(data)
    assert info.duration == 12.5 and not info.has_video and info.acodec == "mp3"
