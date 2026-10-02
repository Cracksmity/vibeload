"""Perfiles, planificación y ejecución de ffmpeg / ffprobe.

Flujo de convert():
  1. ffprobe de la fuente (códec, resolución, fps, audio).
  2. plan_conversion(): decide si se puede copiar el video/audio tal cual
     (remux, segundos) o si hay que recodificar, y a qué tamaño y fps.
  3. Elige encoder: hardware (NVENC / QuickSync / AMF) si funciona, si no CPU.
  4. Ejecuta con progreso por -progress; si el hardware falla, reintenta en CPU.
"""
import collections
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass

from .errors import FfmpegError, TargetSizeTooSmallError, UserCancelledError
from .tools import ffmpeg_exe, ffprobe_exe, no_window_flags

# ============================================================
# PERFILES
# ============================================================


@dataclass(frozen=True)
class FfmpegProfile:
    nice_name: str
    codec: str = "h264"  # "h264" | "hevc"
    max_long: int = 1280  # lado largo máximo (1280 → 1280×720 o 720×1280)
    max_short: int = 720  # lado corto máximo
    fps_cap: float = 30.0  # solo se baja si la fuente supera este valor
    crf: int = 23
    cpu_preset: str = "medium"
    h264_profile: str | None = "main"
    h264_level: str | None = "4.0"
    audio_bitrate: str = "128k"
    audio_sample_rate: int | None = None  # None = conservar 44.1 / 48 kHz
    # Perfiles H.264 (nombres de ffprobe) que se pueden copiar sin recodificar.
    copy_profiles: tuple = ()
    copy_max_level: int = 0  # nivel H.264 máximo copiable (31 = 3.1, 40 = 4.0)


FFMPEG_PROFILE_WHATSAPP = FfmpegProfile(
    nice_name="WhatsApp / móviles",
    crf=23,
    h264_profile="main",
    h264_level="4.0",
    copy_profiles=("Constrained Baseline", "Baseline", "Main", "High"),
    copy_max_level=40,
)

# Baseline + nivel 3.1: sin B-frames ni CABAC, máxima compatibilidad con
# autoestéreos y reproductores antiguos.
FFMPEG_PROFILE_CAR = FfmpegProfile(
    nice_name="Modo Auto (autoestéreo)",
    crf=22,
    h264_profile="baseline",
    h264_level="3.1",
    audio_sample_rate=44100,
    copy_profiles=("Constrained Baseline", "Baseline"),
    copy_max_level=31,
)

# H.265 a 720p para cursos/tutoriales largos: ~40-50 % menos peso que H.264.
FFMPEG_PROFILE_CURSOS = FfmpegProfile(
    nice_name="Cursos (H.265)",
    codec="hevc",
    crf=28,
    h264_profile=None,
    h264_level=None,
    audio_bitrate="96k",
)

# Tamaño objetivo: el bitrate se calcula según la duración (dos pasadas).
FFMPEG_PROFILE_TARGET = FfmpegProfile(
    nice_name="Tamaño máximo",
    max_long=1920,
    max_short=1080,
    h264_profile="main",
    h264_level="4.0",
)

CPU_ENCODERS = {"h264": "libx264", "hevc": "libx265"}
HW_ENCODERS = {
    "h264": ("h264_nvenc", "h264_qsv", "h264_amf"),
    "hevc": ("hevc_nvenc", "hevc_qsv", "hevc_amf"),
}
HW_NAMES = {"nvenc": "NVIDIA NVENC", "qsv": "Intel QuickSync", "amf": "AMD AMF"}


def encoder_label(encoder: str) -> str:
    for k, v in HW_NAMES.items():
        if encoder.endswith(k):
            return f"{v} ({encoder})"
    return f"CPU ({encoder})"


def is_hw_encoder(encoder: str) -> bool:
    return encoder not in CPU_ENCODERS.values()


# ============================================================
# FFPROBE
# ============================================================


@dataclass
class MediaInfo:
    duration: float | None = None
    has_video: bool = False
    width: int = 0
    height: int = 0
    fps: float | None = None
    fps_str: str | None = None
    vcodec: str | None = None
    vprofile: str | None = None
    vlevel: int | None = None
    pix_fmt: str | None = None
    has_audio: bool = False
    acodec: str | None = None
    aprofile: str | None = None
    achannels: int | None = None
    asample_rate: int | None = None


def _parse_rate(r):
    if not r or r in ("0/0", "N/A"):
        return None
    try:
        if "/" in r:
            n, d = r.split("/", 1)
            n, d = float(n), float(d)
            return n / d if d else None
        return float(r)
    except ValueError:
        return None


def parse_ffprobe_json(data: dict) -> MediaInfo:
    info = MediaInfo()
    fmt = data.get("format") or {}
    try:
        info.duration = float(fmt.get("duration")) if fmt.get("duration") not in (None, "N/A") else None
    except (TypeError, ValueError):
        info.duration = None
    for s in data.get("streams") or []:
        t = s.get("codec_type")
        if t == "video" and not info.has_video:
            if (s.get("disposition") or {}).get("attached_pic"):
                continue  # portada embebida, no es video
            info.has_video = True
            info.width = int(s.get("width") or 0)
            info.height = int(s.get("height") or 0)
            rate = s.get("avg_frame_rate")
            if not _parse_rate(rate):
                rate = s.get("r_frame_rate")
            info.fps = _parse_rate(rate)
            info.fps_str = rate if info.fps else None
            info.vcodec = s.get("codec_name")
            info.vprofile = s.get("profile")
            lvl = s.get("level")
            info.vlevel = int(lvl) if isinstance(lvl, int) and lvl > 0 else None
            info.pix_fmt = s.get("pix_fmt")
        elif t == "audio" and not info.has_audio:
            info.has_audio = True
            info.acodec = s.get("codec_name")
            info.aprofile = s.get("profile")
            info.achannels = int(s.get("channels") or 0) or None
            try:
                info.asample_rate = int(s.get("sample_rate") or 0) or None
            except ValueError:
                info.asample_rate = None
    return info


def probe_media(path) -> MediaInfo:
    try:
        r = subprocess.run(
            [ffprobe_exe(), "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=no_window_flags(),
        )
        return parse_ffprobe_json(json.loads(r.stdout or "{}"))
    except (OSError, ValueError):
        return MediaInfo()


def ffprobe_duration_seconds(path):
    return probe_media(path).duration


# ============================================================
# PLANIFICACIÓN
# ============================================================


def fit_dimensions(w: int, h: int, max_long: int, max_short: int):
    """Escala para que el lado largo ≤ max_long y el corto ≤ max_short.

    Respeta la orientación: un vertical 1080×1920 queda 720×1280 (no 405×720).
    Siempre devuelve dimensiones pares (requisito de yuv420p).
    """
    if not w or not h:
        return None
    long_side, short_side = max(w, h), min(w, h)
    f = min(1.0, max_long / long_side, max_short / short_side)
    nw = max(2, int(w * f) // 2 * 2)
    nh = max(2, int(h * f) // 2 * 2)
    return nw, nh


@dataclass
class ConversionPlan:
    video_copy: bool
    audio_copy: bool
    dims: tuple | None  # None = sin escalar
    fps_str: str | None  # None = conservar


def _level_value(level_str: str | None) -> int:
    try:
        return int(round(float(level_str) * 10))
    except (TypeError, ValueError):
        return 0


def plan_conversion(profile: FfmpegProfile, info: MediaInfo, clip=None) -> ConversionPlan:
    dims = fit_dimensions(info.width, info.height, profile.max_long, profile.max_short)
    needs_scale = dims is not None and dims != (info.width, info.height)

    fps_str = None
    if info.fps is None or info.fps > profile.fps_cap + 0.01:
        fps_str = str(int(profile.fps_cap)) if profile.fps_cap == int(profile.fps_cap) else str(profile.fps_cap)

    video_copy = (
        info.has_video
        and profile.codec == "h264"
        and info.vcodec == "h264"
        and info.vprofile in profile.copy_profiles
        and (info.vlevel or 999) <= profile.copy_max_level
        and info.pix_fmt == "yuv420p"
        and not needs_scale
        and fps_str is None
        and not clip  # un corte con copia caería en keyframes, no en el segundo exacto
    )

    sr_ok = (
        info.asample_rate == profile.audio_sample_rate
        if profile.audio_sample_rate
        else info.asample_rate in (44100, 48000)
    )
    audio_copy = (
        info.has_audio
        and info.acodec == "aac"
        and (info.aprofile in (None, "LC"))
        and (info.achannels or 0) in (1, 2)
        and sr_ok
    )
    return ConversionPlan(video_copy, audio_copy, dims if needs_scale else None, fps_str)


def target_bitrates(target_mb: float, duration: float, has_audio: bool = True):
    """(video_kbps, audio_kbps, (max_long, max_short)) para que el archivo pese ≤ target_mb.

    target_mb usa MiB (como WhatsApp/Discord/Windows). Se deja ~4 % de margen
    para el contenedor y las variaciones del encoder.
    """
    if not duration or duration <= 0:
        raise TargetSizeTooSmallError("No se conoce la duración del video; no se puede calcular el tamaño.")
    total_kbps = target_mb * 8388.608 / duration * 0.96
    if not has_audio:
        audio = 0
    elif total_kbps > 1500:
        audio = 128
    elif total_kbps > 600:
        audio = 96
    else:
        audio = 64
    video = int(total_kbps - audio)
    if video < 100:
        raise TargetSizeTooSmallError(
            f"Para que pese {target_mb:g} MB, este video ({duration / 60:.1f} min) quedaría "
            "con una calidad inservible. Elige más MB o recorta un fragmento más corto."
        )
    if video >= 2500:
        box = (1920, 1080)
    elif video >= 1200:
        box = (1280, 720)
    elif video >= 600:
        box = (854, 480)
    else:
        box = (640, 360)
    return video, audio, box


# ============================================================
# ENCODERS (CPU / HARDWARE)
# ============================================================

_hw_cache: dict = {}
_hw_lock = threading.Lock()


def _list_encoders() -> set:
    try:
        r = subprocess.run(
            [ffmpeg_exe(), "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
            creationflags=no_window_flags(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return set()
    out = set()
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            out.add(parts[1])
    return out


def _hw_pix_fmt(encoder: str) -> str:
    return "nv12" if encoder.endswith(("_qsv", "_amf")) else "yuv420p"


def _test_encoder(encoder: str) -> bool:
    """Que ffmpeg liste un encoder no significa que exista el hardware: se prueba."""
    try:
        r = subprocess.run(
            [
                ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=640x360:r=30:d=0.5",
                "-frames:v", "10", "-c:v", encoder, "-pix_fmt", _hw_pix_fmt(encoder),
                "-f", "null", "-",
            ],
            capture_output=True,
            timeout=20,
            creationflags=no_window_flags(),
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def detect_hw_encoder(codec: str) -> str | None:
    """Primer encoder de hardware que funciona de verdad para el códec (con caché)."""
    with _hw_lock:
        if codec in _hw_cache:
            return _hw_cache[codec]
        available = _list_encoders()
        found = None
        for enc in HW_ENCODERS.get(codec, ()):
            if enc in available and _test_encoder(enc):
                found = enc
                break
        _hw_cache[codec] = found
        return found


def mark_hw_broken(codec: str):
    with _hw_lock:
        _hw_cache[codec] = None


def pick_encoder(codec: str, encoder_mode: str = "auto") -> str:
    if encoder_mode == "auto":
        hw = detect_hw_encoder(codec)
        if hw:
            return hw
    return CPU_ENCODERS[codec]


def video_encoder_args(encoder: str, profile: FfmpegProfile, bitrate_k: int | None = None) -> list:
    """Argumentos de calidad / perfil para cada encoder."""
    a = ["-c:v", encoder]
    q = profile.crf
    baseline = profile.h264_profile == "baseline"

    if encoder == "libx264":
        a += ["-preset", profile.cpu_preset]
        if bitrate_k:
            a += ["-b:v", f"{bitrate_k}k"]
        else:
            a += ["-crf", str(q)]
        if profile.h264_profile:
            a += ["-profile:v", profile.h264_profile]
        if profile.h264_level:
            a += ["-level", profile.h264_level]
    elif encoder == "libx265":
        a += ["-preset", profile.cpu_preset, "-crf", str(q), "-x265-params", "log-level=error"]
    elif encoder.endswith("_nvenc"):
        a += ["-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", str(q + 2), "-b:v", "0"]
        if encoder.startswith("h264") and profile.h264_profile:
            a += ["-profile:v", profile.h264_profile]
            if profile.h264_level:
                a += ["-level", profile.h264_level]
    elif encoder.endswith("_qsv"):
        a += ["-preset", "medium", "-global_quality", str(q + 2)]
        if encoder.startswith("h264") and profile.h264_profile:
            a += ["-profile:v", profile.h264_profile]
    elif encoder.endswith("_amf"):
        # Calibrado con contenido real (RX 6600): QP = CRF+4 en H.264 y CRF+2 en
        # HEVC dan el mismo peso que libx264/libx265 con calidad (SSIM) parecida.
        qp = str(q + (4 if encoder.startswith("h264") else 2))
        a += ["-quality", "balanced", "-rc", "cqp", "-qp_i", qp, "-qp_p", qp]
        if encoder.startswith("h264"):
            a += ["-qp_b", qp]
            if profile.h264_profile:
                a += ["-profile:v", "constrained_baseline" if baseline else profile.h264_profile]

    if baseline and encoder.startswith(("h264", "libx264")):
        a += ["-bf", "0"]
    a += ["-pix_fmt", "yuv420p" if not is_hw_encoder(encoder) else _hw_pix_fmt(encoder)]
    if profile.codec == "hevc":
        a += ["-tag:v", "hvc1"]  # necesario para que Apple/Windows reconozcan HEVC en MP4
    return a


# ============================================================
# COMANDO
# ============================================================


def build_convert_cmd(
    src,
    dst,
    profile: FfmpegProfile,
    plan: ConversionPlan,
    info: MediaInfo,
    *,
    encoder: str | None = None,
    clip=None,
    bitrate_k: int | None = None,
    audio_kbps: int | None = None,
    pass_no: int | None = None,
    passlog: str | None = None,
) -> list:
    cmd = [ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats", "-y"]
    if clip:
        s, e = clip
        if s:
            cmd += ["-ss", f"{s:.3f}"]  # antes de -i: búsqueda rápida y exacta al recodificar
        cmd += ["-i", src]
        if e is not None:
            cmd += ["-t", f"{e - (s or 0):.3f}"]
    else:
        cmd += ["-i", src]

    cmd += ["-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn", "-map_metadata", "0"]

    if plan.video_copy:
        cmd += ["-c:v", "copy"]
    else:
        vf = []
        if plan.dims:
            vf.append(f"scale={plan.dims[0]}:{plan.dims[1]}")
        if plan.fps_str:
            vf.append(f"fps={plan.fps_str}")
        vf.append("setsar=1")
        cmd += ["-vf", ",".join(vf)]
        cmd += video_encoder_args(encoder or CPU_ENCODERS[profile.codec], profile, bitrate_k)

    if pass_no:
        cmd += ["-pass", str(pass_no), "-passlogfile", passlog]
    if pass_no == 1:
        cmd += ["-an", "-f", "null", "-"]
        return cmd

    if not info.has_audio:
        cmd += ["-an"]
    elif plan.audio_copy and not audio_kbps:
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", f"{audio_kbps}k" if audio_kbps else profile.audio_bitrate]
        sr = profile.audio_sample_rate or (info.asample_rate if info.asample_rate in (44100, 48000) else 48000)
        cmd += ["-ar", str(sr), "-ac", "2"]

    cmd += ["-movflags", "+faststart", dst]
    return cmd


# ============================================================
# EJECUCIÓN
# ============================================================


def _last_error_line(lines) -> str:
    for line in reversed(list(lines)):
        s = line.strip()
        if s and not s.startswith("frame="):
            return s
    return ""


def run_ffmpeg_cmd(
    cmd,
    duration,
    *,
    logger,
    emit_progress,
    cancel_event,
    proc_holder,
    pct_lo,
    pct_hi,
    label="Convirtiendo",
):
    """Ejecuta ffmpeg leyendo -progress en stdout y guardando la cola de stderr."""
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=no_window_flags(),
        )
    except FileNotFoundError:
        raise FfmpegError("No se encontró ffmpeg. Instálalo o deja que VibeLoader lo descargue.")

    if proc_holder is not None:
        proc_holder["p"] = proc

    tail = collections.deque(maxlen=40)

    def _drain_stderr():
        for line in iter(proc.stderr.readline, ""):
            tail.append(line.rstrip())

    t_err = threading.Thread(target=_drain_stderr, daemon=True)
    t_err.start()

    pct_lo = max(0, min(100, int(pct_lo)))
    pct_hi = max(0, min(100, int(pct_hi)))
    span = max(1, pct_hi - pct_lo)
    last_emit = 0.0
    speed = ""

    try:
        for line in iter(proc.stdout.readline, ""):
            if cancel_event is not None and cancel_event.is_set():
                proc.terminate()
                raise UserCancelledError("Cancelado durante la conversión")
            key, _, val = line.strip().partition("=")
            if key == "speed":
                speed = val.strip()
            elif key in ("out_time_us", "out_time_ms") and emit_progress and duration:
                try:
                    cur = int(val) / 1_000_000
                except ValueError:
                    continue
                sub = min(1.0, max(0.0, cur / duration))
                p = int(pct_lo + sub * span)
                now = time.monotonic()
                if now - last_emit >= 0.3:
                    last_emit = now
                    msg = f"{label} {int(sub * 100)}%"
                    if speed and speed not in ("N/A", "0x"):
                        msg += f" · {speed}"
                    emit_progress(min(p, pct_hi), msg)
    finally:
        if proc_holder is not None:
            proc_holder["p"] = None
        try:
            ret = proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
            ret = -1
        t_err.join(timeout=5)

    if cancel_event is not None and cancel_event.is_set():
        raise UserCancelledError("Cancelado durante la conversión")
    if ret != 0:
        for line in list(tail)[-15:]:
            logger("  ffmpeg: " + line)
        reason = _last_error_line(tail) or f"código de salida {ret}"
        raise FfmpegError(f"FFmpeg falló: {reason}")
    if emit_progress:
        emit_progress(pct_hi, f"{label}: listo")


def _describe(plan: ConversionPlan, encoder: str | None) -> str:
    if plan.video_copy and plan.audio_copy:
        return "⚡ La fuente ya es compatible: se copia sin recodificar (remux)."
    parts = []
    parts.append("video copiado sin recodificar" if plan.video_copy else f"video con {encoder_label(encoder)}")
    parts.append("audio copiado" if plan.audio_copy else "audio a AAC")
    extra = []
    if plan.dims and not plan.video_copy:
        extra.append(f"{plan.dims[0]}×{plan.dims[1]}")
    if plan.fps_str and not plan.video_copy:
        extra.append(f"{plan.fps_str} fps")
    return "🎬 " + ", ".join(parts) + (f" ({', '.join(extra)})" if extra else "")


def convert(
    src,
    dst,
    profile: FfmpegProfile,
    *,
    clip=None,
    encoder_mode: str = "auto",
    target_mb: float | None = None,
    logger=print,
    emit_progress=None,
    cancel_event=None,
    proc_holder=None,
    pct_lo=0,
    pct_hi=100,
):
    """Convierte src → dst según el perfil. clip = (inicio, fin|None) en segundos."""
    logger(f"🎬 Procesando con ffmpeg ({profile.nice_name})…")
    info = probe_media(src)
    if not info.has_video and not info.has_audio:
        raise FfmpegError("FFmpeg falló: el archivo descargado no tiene pistas legibles.")
    duration = info.duration
    if clip:
        s, e = clip
        end = e if e is not None else (duration or 0)
        duration = max(0.0, end - (s or 0)) or duration
    kw = dict(
        logger=logger,
        emit_progress=emit_progress,
        cancel_event=cancel_event,
        proc_holder=proc_holder,
    )

    if target_mb:
        return _convert_target_size(src, dst, profile, info, clip, duration, target_mb, pct_lo, pct_hi, kw)

    plan = plan_conversion(profile, info, clip)
    encoder = None if plan.video_copy else pick_encoder(profile.codec, encoder_mode)
    logger(_describe(plan, encoder))
    cmd = build_convert_cmd(src, dst, profile, plan, info, encoder=encoder, clip=clip)
    try:
        run_ffmpeg_cmd(cmd, duration, pct_lo=pct_lo, pct_hi=pct_hi, **kw)
    except FfmpegError:
        if not encoder or not is_hw_encoder(encoder):
            raise
        logger(f"⚠️ Falló {encoder_label(encoder)}; reintentando con CPU…")
        mark_hw_broken(profile.codec)
        encoder = CPU_ENCODERS[profile.codec]
        cmd = build_convert_cmd(src, dst, profile, plan, info, encoder=encoder, clip=clip)
        run_ffmpeg_cmd(cmd, duration, pct_lo=pct_lo, pct_hi=pct_hi, **kw)
    logger(f"✅ Conversión terminada: {dst}")


def _convert_target_size(src, dst, profile, info, clip, duration, target_mb, pct_lo, pct_hi, kw):
    logger = kw["logger"]
    limit_bytes = target_mb * 1024 * 1024

    plan = plan_conversion(FFMPEG_PROFILE_WHATSAPP, info, clip)
    if not clip and plan.video_copy and plan.audio_copy and os.path.getsize(src) <= limit_bytes:
        logger(f"⚡ Ya pesa menos de {target_mb:g} MB y es compatible: se copia sin recodificar.")
        cmd = build_convert_cmd(src, dst, profile, plan, info, clip=clip)
        run_ffmpeg_cmd(cmd, duration, pct_lo=pct_lo, pct_hi=pct_hi, **kw)
        return

    video_k, audio_k, box = target_bitrates(target_mb, duration, info.has_audio)
    dims = fit_dimensions(info.width, info.height, min(box[0], profile.max_long), min(box[1], profile.max_short))
    fps_str = None
    if info.fps is None or info.fps > profile.fps_cap + 0.01:
        fps_str = str(int(profile.fps_cap))
    plan = ConversionPlan(
        video_copy=False,
        audio_copy=False,
        dims=dims if dims and dims != (info.width, info.height) else None,
        fps_str=fps_str,
    )
    res = f"{dims[0]}×{dims[1]}" if dims else "original"
    logger(
        f"🎯 Objetivo {target_mb:g} MB → video {video_k} kbps, audio {audio_k} kbps, {res}. "
        "Dos pasadas con CPU (libx264) para clavar el tamaño."
    )
    tmpdir = tempfile.mkdtemp(prefix="vibeload_pass_")
    passlog = os.path.join(tmpdir, "pass")
    mid = pct_lo + (pct_hi - pct_lo) // 3
    try:
        cmd1 = build_convert_cmd(src, dst, profile, plan, info, encoder="libx264", clip=clip, bitrate_k=video_k, pass_no=1, passlog=passlog)
        run_ffmpeg_cmd(cmd1, duration, pct_lo=pct_lo, pct_hi=mid, label="Analizando (1/2)", **kw)
        cmd2 = build_convert_cmd(
            src, dst, profile, plan, info, encoder="libx264", clip=clip,
            bitrate_k=video_k, audio_kbps=audio_k or None, pass_no=2, passlog=passlog,
        )
        run_ffmpeg_cmd(cmd2, duration, pct_lo=mid, pct_hi=pct_hi, label="Comprimiendo (2/2)", **kw)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    size_mb = os.path.getsize(dst) / 1024 / 1024
    logger(f"✅ Listo: {size_mb:.1f} MB (objetivo {target_mb:g} MB).")
