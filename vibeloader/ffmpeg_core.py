"""Perfiles y ejecución de ffmpeg / ffprobe."""
import re
import subprocess
import sys
import time
from dataclasses import dataclass

from .errors import UserCancelledError

FFMPEG_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.?\d*)")


def ffprobe_duration_seconds(path):
    try:
        creation = 0
        if sys.platform == "win32":
            creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            check=False,
            creationflags=creation,
        )
        v = (r.stdout or "").strip()
        if not v or v.lower() == "n/a":
            return None
        return float(v)
    except (ValueError, OSError):
        return None


_H264_720P_VF = (
    "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease,"
    "scale=trunc(iw/2)*2:trunc(ih/2)*2"
)


@dataclass(frozen=True)
class FfmpegProfile:
    nice_name: str
    vf: str
    fps: int
    video_codec: str
    crf: int
    preset: str
    audio_bitrate: str
    audio_sample_rate: int | None = 48000
    audio_channels: int = 2
    h264_profile: str | None = None
    h264_level: str | None = None
    extra_video_args: tuple = ()


FFMPEG_PROFILE_WHATSAPP = FfmpegProfile(
    nice_name="WhatsApp / móviles",
    vf=_H264_720P_VF,
    fps=30,
    video_codec="libx264",
    crf=23,
    preset="medium",
    audio_bitrate="128k",
    audio_sample_rate=48000,
    h264_profile="main",
    h264_level="4.0",
    extra_video_args=("-pix_fmt", "yuv420p"),
)

FFMPEG_PROFILE_CAR = FfmpegProfile(
    nice_name="Modo Auto (autoestéreo)",
    vf=_H264_720P_VF,
    fps=30,
    video_codec="libx264",
    crf=22,
    preset="medium",
    audio_bitrate="128k",
    audio_sample_rate=44100,
    h264_profile="baseline",
    h264_level="3.1",
    extra_video_args=("-pix_fmt", "yuv420p"),
)

def _build_ffmpeg_cmd(src, dst, profile: FfmpegProfile) -> list:
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "info",
        "-stats",
        "-y",
        "-i",
        src,
        "-vf",
        profile.vf,
        "-r",
        str(profile.fps),
        "-c:v",
        profile.video_codec,
    ]
    if profile.video_codec == "libx264":
        cmd.extend(
            ["-profile:v", profile.h264_profile, "-level", profile.h264_level]
        )
    if profile.extra_video_args:
        cmd.extend(profile.extra_video_args)
    cmd.extend(
        [
            "-crf",
            str(profile.crf),
            "-preset",
            profile.preset,
            "-c:a",
            "aac",
            "-b:a",
            profile.audio_bitrate,
        ]
    )
    if profile.audio_sample_rate is not None:
        cmd.extend(["-ar", str(profile.audio_sample_rate)])
    cmd.extend(
        [
            "-ac",
            str(profile.audio_channels),
            "-movflags",
            "+faststart",
            dst,
        ]
    )
    return cmd


def _run_ffmpeg(
    cmd,
    src,
    dst,
    logger,
    emit_progress,
    cancel_event,
    proc_holder,
    pct_lo,
    pct_hi,
    nice_name,
):
    logger(f"🎬 Recompresión con ffmpeg ({nice_name})…")
    duration = ffprobe_duration_seconds(src)

    creation = 0
    if sys.platform == "win32":
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        proc = subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            text=True,
            errors="replace",
            bufsize=1,
            creationflags=creation,
        )
    except FileNotFoundError:
        logger("❌ No se encontró 'ffmpeg' en el PATH.")
        raise

    if proc_holder is not None:
        proc_holder["p"] = proc

    pct_lo = max(0, min(100, int(pct_lo)))
    pct_hi = max(0, min(100, int(pct_hi)))
    span = max(1, pct_hi - pct_lo)
    last_p = -1
    last_t = 0.0

    try:
        assert proc.stderr is not None
        for line in iter(proc.stderr.readline, ""):
            if cancel_event is not None and cancel_event.is_set():
                proc.terminate()
                raise UserCancelledError("Cancelado durante la conversión")
            if emit_progress:
                m = FFMPEG_TIME_RE.search(line)
                if m and duration and duration > 0:
                    h, mi, sec = int(m.group(1)), int(m.group(2)), float(m.group(3))
                    cur = h * 3600 + mi * 60 + sec
                    sub = min(1.0, max(0.0, cur / duration))
                    p = int(pct_lo + sub * span)
                    now = time.monotonic()
                    if p != last_p or now - last_t >= 0.35:
                        last_p = p
                        last_t = now
                        emit_progress(min(p, pct_hi), f"Convirtiendo {p}%")
    finally:
        if proc_holder is not None:
            proc_holder["p"] = None
        try:
            ret = proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
            ret = -1

    if cancel_event is not None and cancel_event.is_set():
        raise UserCancelledError("Cancelado durante la conversión")
    if ret != 0:
        raise subprocess.CalledProcessError(ret, cmd)

    if emit_progress:
        emit_progress(pct_hi, "Conversión lista")
    logger(f"✅ Conversión ffmpeg terminada: {dst}")


def _run_ffmpeg_with_profile(
    src,
    dst,
    logger,
    emit_progress,
    cancel_event,
    proc_holder,
    pct_lo,
    pct_hi,
    profile: FfmpegProfile,
):
    cmd = _build_ffmpeg_cmd(src, dst, profile)
    return _run_ffmpeg(
        cmd,
        src,
        dst,
        logger,
        emit_progress,
        cancel_event,
        proc_holder,
        pct_lo,
        pct_hi,
        profile.nice_name,
    )


def run_ffmpeg_whatsapp(
    src, dst, logger, emit_progress, cancel_event, proc_holder, pct_lo, pct_hi
):
    """H.264 Main@L4.0, máx 1280x720, 30 fps, AAC LC 128k, +faststart."""
    return _run_ffmpeg_with_profile(
        src,
        dst,
        logger,
        emit_progress,
        cancel_event,
        proc_holder,
        pct_lo,
        pct_hi,
        FFMPEG_PROFILE_WHATSAPP,
    )


def run_ffmpeg_car(
    src, dst, logger, emit_progress, cancel_event, proc_holder, pct_lo, pct_hi
):
    """H.264 Baseline@L3.1, máx 1280x720, 30 fps, AAC LC 128k 44.1 kHz, +faststart.

    Profile Baseline + level 3.1 dan máxima compatibilidad con autoestéreos y
    reproductores antiguos (sin B-frames, sin CABAC).
    """
    return _run_ffmpeg_with_profile(
        src,
        dst,
        logger,
        emit_progress,
        cancel_event,
        proc_holder,
        pct_lo,
        pct_hi,
        FFMPEG_PROFILE_CAR,
    )
