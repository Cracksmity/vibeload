"""Todo lo que habla con yt-dlp: opciones, descarga y metadatos."""
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field

from .config import META_YTDLP_IMPERSONATE, is_frozen
from .errors import ClipTimestampError, PlaylistNotSupportedError, UserCancelledError
from .thumbnails import collect_thumbnail_urls
from .tools import ffmpeg_location_for_ytdlp, no_window_flags
from .urls import _host_is_meta, _host_is_youtube, _url_hostname_lower
from .utils import format_duration, parse_time

_ytdlp_youtube_dl = None
_ytdlp_download_range_func = None


def _import_ytdlp():
    """Import yt-dlp on first use only (large cold-start cost at module import)."""
    global _ytdlp_youtube_dl, _ytdlp_download_range_func
    if _ytdlp_youtube_dl is None:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import download_range_func

        _ytdlp_youtube_dl = YoutubeDL
        _ytdlp_download_range_func = download_range_func
    return _ytdlp_youtube_dl, _ytdlp_download_range_func


def ytdlp_version() -> str:
    try:
        from yt_dlp.version import __version__

        return __version__
    except Exception:
        return "desconocida"


# ============================================================
# PRESETS DE DESCARGA
# ============================================================

# yt-dlp mide "res" con el lado CORTO del video, así que "res:720" respeta
# videos verticales (Shorts/TikTok/Reels quedan 720×1280, no 405×720).
# Preferir H.264 + AAC evita AV1/VP9/Opus dentro de MP4 (no se reproducen en
# autoestéreos, TVs ni en el reproductor de Windows) y evita fuentes HDR, que
# salen con colores lavados al convertir a yuv420p sin tonemapping.


@dataclass(frozen=True)
class DownloadSpec:
    format: str
    outtmpl: str
    format_sort: tuple = ()
    merge_output_format: str | None = "mp4"
    restrictfilenames: bool = False
    writethumbnail: bool = False
    postprocessors: tuple = field(default_factory=tuple)


# Fuente para recomprimir con ffmpeg (WhatsApp, Auto, Cursos, tamaño objetivo).
SPEC_CONVERT_SOURCE = DownloadSpec(
    format="bv*+ba/b",
    format_sort=("res:720", "vcodec:h264", "acodec:aac"),
    outtmpl="%(id)s.vlsrc.%(ext)s",
    restrictfilenames=True,
)

# Fuente para el Modo Tamaño Máximo: hasta 1080p (el bitrate decide la escala final).
SPEC_CONVERT_SOURCE_1080 = DownloadSpec(
    format="bv*+ba/b",
    format_sort=("res:1080", "vcodec:h264", "acodec:aac"),
    outtmpl="%(id)s.vlsrc.%(ext)s",
    restrictfilenames=True,
)

# "Descargar Video": hasta 1080p, sin recomprimir, MP4 compatible.
SPEC_MAX = DownloadSpec(
    format="bv*+ba/b",
    format_sort=("res:1080", "vcodec:h264", "acodec:aac"),
    outtmpl="%(title)s.%(ext)s",
)

# "Descarga Directa": 720p H.264 + AAC unidos sin recodificar (remux).
# Los formatos progresivos (video+audio en un archivo) de YouTube ya solo
# llegan a 360p, por eso se unen las pistas separadas.
SPEC_DIRECTO = DownloadSpec(
    format="bv*[vcodec^=avc1]+ba[ext=m4a]/bv*[vcodec^=avc1]+ba/b[ext=mp4]/b",
    format_sort=("res:720",),
    outtmpl="%(title)s.%(ext)s",
)

SPEC_MP3 = DownloadSpec(
    format="bestaudio/best",
    outtmpl="%(title)s.%(ext)s",
    merge_output_format=None,
    writethumbnail=True,
    postprocessors=(
        {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
        {"key": "FFmpegMetadata"},
        {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
        {"key": "EmbedThumbnail"},
    ),
)


# ============================================================
# OPCIONES POR SITIO
# ============================================================


def _merge_meta_impersonate_ytdlp_opts(url: str, ydl_opts: dict) -> dict:
    """Solo dominios Meta (Facebook, Instagram, …). Nunca YouTube."""
    if _host_is_meta(_url_hostname_lower(url)):
        try:
            from yt_dlp.networking.impersonate import ImpersonateTarget

            ydl_opts["impersonate"] = ImpersonateTarget.from_str(META_YTDLP_IMPERSONATE)
        except Exception:
            ydl_opts["impersonate"] = META_YTDLP_IMPERSONATE
    return ydl_opts


def _merge_youtube_opts(url: str, ydl_opts: dict) -> dict:
    """YouTube: habilita todos los runtimes de JS que yt-dlp sepa usar.

    No se fuerza player_client: los clientes por defecto de yt-dlp son los que
    sus mantenedores ajustan cada vez que YouTube cambia algo.
    """
    if _host_is_youtube(_url_hostname_lower(url)):
        ydl_opts.setdefault(
            "js_runtimes", {"deno": {}, "node": {}, "bun": {}, "quickjs": {}}
        )
    return ydl_opts


def _is_impersonate_unavailable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "impersonate target" in msg and "not available" in msg


class _YdlLogger:
    """Redirige la salida de yt-dlp al log de la app (antes se perdía)."""

    def __init__(self, log, verbose: bool = True):
        self._log = log
        self._verbose = verbose

    def debug(self, msg):
        if msg.startswith("[debug] "):
            return
        self.info(msg)

    def info(self, msg):
        if self._verbose and self._log:
            self._log(msg)

    def warning(self, msg):
        if self._log:
            self._log("⚠️ yt-dlp: " + msg)

    def error(self, msg):
        if self._log:
            self._log("❌ yt-dlp: " + msg)


def base_ydl_opts(url: str, logger=None, verbose: bool = True) -> dict:
    opts = {
        "noplaylist": True,
        "noprogress": True,
        "windowsfilenames": True,
        "logger": _YdlLogger(logger, verbose=verbose),
    }
    ff = ffmpeg_location_for_ytdlp()
    if ff:
        opts["ffmpeg_location"] = ff
    _merge_meta_impersonate_ytdlp_opts(url, opts)
    _merge_youtube_opts(url, opts)
    return opts


def _with_ydl(opts: dict, logger, work):
    """Ejecuta work(ydl); si falta la huella TLS (curl_cffi), reintenta sin ella."""
    YoutubeDL, _ = _import_ytdlp()
    try:
        with YoutubeDL(opts) as ydl:
            return work(ydl)
    except Exception as e:
        if "impersonate" not in opts or not _is_impersonate_unavailable(e):
            raise
        if logger:
            logger("⚠️ Impersonate no disponible en esta build; reintentando sin impersonate…")
        opts2 = dict(opts)
        opts2.pop("impersonate", None)
        with YoutubeDL(opts2) as ydl:
            return work(ydl)


def _resolve_url_results(ydl, ie_result: dict, max_hops: int = 5) -> dict:
    """Sigue redirecciones '_type: url' (fb.watch, acortadores) sin procesar formatos."""
    hops = 0
    while ie_result.get("_type") in ("url", "url_transparent") and hops < max_hops:
        nxt = ydl.extract_info(
            ie_result["url"], ie_key=ie_result.get("ie_key"), download=False, process=False
        )
        if ie_result.get("_type") == "url_transparent":
            merged = {k: v for k, v in ie_result.items() if v is not None and k not in ("_type", "url", "ie_key")}
            merged.update(nxt)
            nxt = merged
        ie_result = nxt
        hops += 1
    return ie_result


def _is_playlist(ie_result: dict) -> bool:
    return ie_result.get("_type") in ("playlist", "multi_video")


# ============================================================
# PROGRESO
# ============================================================


def make_ydl_progress_hook(cancel_event, pct_lo, pct_hi, emit):
    """Mapea el progreso de yt-dlp a [pct_lo, pct_hi].

    Cuando el video y el audio se bajan por separado, el video ocupa el 85 %
    del tramo y el audio el resto, para que la barra no vuelva a 0.
    """
    pct_lo = max(0, min(100, int(pct_lo)))
    pct_hi = max(0, min(100, int(pct_hi)))
    if pct_hi < pct_lo:
        pct_lo, pct_hi = pct_hi, pct_lo
    span = max(1, pct_hi - pct_lo)
    split = pct_lo + int(span * 0.85)
    state = {"video_only_seen": False}

    def _segment(info):
        vc = (info or {}).get("vcodec")
        ac = (info or {}).get("acodec")
        has_v = vc not in (None, "none")
        has_a = ac not in (None, "none")
        if has_v and not has_a:
            state["video_only_seen"] = True
            return pct_lo, split, "Descargando video"
        if has_a and not has_v and state["video_only_seen"]:
            return split, pct_hi, "Descargando audio"
        return pct_lo, pct_hi, "Descargando"

    def hook(d):
        if cancel_event is not None and cancel_event.is_set():
            raise UserCancelledError("Cancelado por el usuario")
        if emit is None:
            return
        st = d.get("status")
        lo, hi, label = _segment(d.get("info_dict"))
        if st == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            speed = (d.get("_speed_str") or "").strip()
            eta = (d.get("_eta_str") or "").strip()
            if total and total > 0:
                sub = min(1.0, max(0.0, done / float(total)))
                p = int(lo + sub * (hi - lo))
                msg = f"{label} {p}%"
            else:
                p = lo
                msg = f"{label}…"
            if speed and not speed.lower().startswith("unknown"):
                msg += f" · {speed}"
            if eta and eta.lower() not in ("unknown", "--:--"):
                msg += f" · quedan {eta}"
            emit(min(p, pct_hi), msg)
        elif st == "finished":
            emit(hi, f"{label}: terminado")

    return hook


def make_pp_hook(cancel_event, pct_hi, emit):
    names = {
        "Merger": "Uniendo video y audio…",
        "FFmpegExtractAudio": "Convirtiendo a MP3…",
        "EmbedThumbnail": "Agregando portada…",
        "FFmpegMetadata": "Escribiendo metadatos…",
    }

    def hook(d):
        if cancel_event is not None and cancel_event.is_set():
            raise UserCancelledError("Cancelado por el usuario")
        if emit is not None and d.get("status") == "started":
            emit(pct_hi, names.get(d.get("postprocessor"), "Postproceso…"))

    return hook


# ============================================================
# RECORTES
# ============================================================

_CLIP_TIME_EPS = 1e-3


def clip_range_requested(start_time, end_time) -> bool:
    return parse_time(start_time) is not None or parse_time(end_time) is not None


def clip_seconds(start_time, end_time):
    """(inicio, fin|None) en segundos, o None si no se pidió recorte."""
    if not clip_range_requested(start_time, end_time):
        return None
    s = parse_time(start_time)
    e = parse_time(end_time)
    return (s if s is not None else 0.0, e)


def validate_clip_against_duration(start_time, end_time, duration: float) -> None:
    start_sec = parse_time(start_time)
    end_sec = parse_time(end_time)
    if start_sec is None and end_sec is None:
        return

    s = start_sec if start_sec is not None else 0.0
    hint = (
        f"Duración del video: {duration:.2f} s (hasta {format_duration(duration)}). "
        "Los tiempos válidos van de 0 s hasta ese momento; el inicio debe ser menor que el fin."
    )

    if s < -_CLIP_TIME_EPS:
        raise ClipTimestampError(f"El tiempo de inicio no puede ser negativo. {hint}")

    if end_sec is None:
        if s >= duration - _CLIP_TIME_EPS:
            raise ClipTimestampError(
                f"El tiempo de inicio ({s:.2f} s) está en el final del video o más allá; "
                f"no queda fragmento que recortar. {hint}"
            )
        return

    e = float(end_sec)
    if e > duration + _CLIP_TIME_EPS:
        raise ClipTimestampError(
            f"El tiempo de fin ({e:.2f} s) supera la duración del video ({duration:.2f} s). {hint}"
        )
    if s >= e - _CLIP_TIME_EPS:
        raise ClipTimestampError(
            f"El tiempo de inicio debe ser estrictamente anterior al de fin "
            f"(inicio {s:.2f} s, fin {e:.2f} s). {hint}"
        )


def _validate_clip_for_info(start_time, end_time, ie_result: dict):
    if not clip_range_requested(start_time, end_time):
        return
    d = ie_result.get("duration")
    try:
        duration = float(d) if d is not None else None
    except (TypeError, ValueError):
        duration = None
    if not duration or duration <= 0:
        raise ClipTimestampError(
            "No se pudo obtener la duración del video (puede ser una transmisión en "
            "vivo o el sitio no publica esa información). No se puede recortar por "
            "tiempo sin conocer la duración."
        )
    validate_clip_against_duration(start_time, end_time, duration)


# ============================================================
# DESCARGA
# ============================================================


@dataclass
class DownloadResult:
    path: str
    info: dict


def _final_filepath(ydl, info: dict) -> str:
    """Ruta real del archivo final (después de unir pistas o convertir a MP3)."""
    for d in info.get("requested_downloads") or ():
        fp = d.get("filepath")
        if fp:
            return fp
    fp = info.get("filepath")
    if fp:
        return fp
    return ydl.prepare_filename(info)


def build_download_opts(url, folder, spec: DownloadSpec, logger, hooks=(), pp_hooks=()):
    opts = base_ydl_opts(url, logger)
    opts["outtmpl"] = os.path.join(folder, spec.outtmpl)
    opts["format"] = spec.format
    if spec.format_sort:
        opts["format_sort"] = list(spec.format_sort)
    if spec.merge_output_format:
        opts["merge_output_format"] = spec.merge_output_format
    if spec.restrictfilenames:
        opts["restrictfilenames"] = True
    if spec.writethumbnail:
        opts["writethumbnail"] = True
    if spec.postprocessors:
        opts["postprocessors"] = [dict(p) for p in spec.postprocessors]
    if hooks:
        opts["progress_hooks"] = list(hooks)
    if pp_hooks:
        opts["postprocessor_hooks"] = list(pp_hooks)
    return opts


def download(
    url,
    folder,
    spec: DownloadSpec,
    *,
    start_time=None,
    end_time=None,
    cut_with_ytdlp=True,
    logger=print,
    cancel_event=None,
    emit_progress=None,
    pct_lo=0,
    pct_hi=95,
) -> DownloadResult:
    """Descarga con un solo paso de extracción.

    1. Extrae sin procesar (detecta playlists y obtiene la duración).
    2. Valida el recorte contra la duración real.
    3. Procesa y descarga.

    Si cut_with_ytdlp es False, el recorte NO se aplica aquí: lo hace ffmpeg en
    la misma pasada de recompresión (evita codificar dos veces).
    """
    os.makedirs(folder, exist_ok=True)
    opts = build_download_opts(
        url,
        folder,
        spec,
        logger,
        hooks=[make_ydl_progress_hook(cancel_event, pct_lo, pct_hi, emit_progress)],
        pp_hooks=[make_pp_hook(cancel_event, pct_hi, emit_progress)],
    )
    clip = clip_seconds(start_time, end_time)
    if clip and cut_with_ytdlp:
        s, e = clip
        _, download_range_func = _import_ytdlp()
        opts["download_ranges"] = download_range_func(None, [(s, e if e is not None else float("inf"))])
        opts["force_keyframes_at_cuts"] = True
        logger(f"✂️ Fragmento: de {s}s hasta {e if e is not None else 'el final'}{'s' if e is not None else ''}")

    def work(ydl):
        if emit_progress:
            emit_progress(pct_lo, "Leyendo información del enlace…")
        ie = ydl.extract_info(url, download=False, process=False)
        ie = _resolve_url_results(ydl, ie)
        if _is_playlist(ie):
            raise PlaylistNotSupportedError(ie.get("title") or "")
        _validate_clip_for_info(start_time, end_time, ie)
        if cancel_event is not None and cancel_event.is_set():
            raise UserCancelledError("Cancelado por el usuario")
        info = ydl.process_ie_result(ie, download=True)
        return DownloadResult(_final_filepath(ydl, info), info)

    return _with_ydl(opts, logger, work)


# ============================================================
# METADATOS (vista previa)
# ============================================================


def fetch_metadata(url: str, logger=None) -> dict:
    """Info para la vista previa. Las playlists se leen en modo plano (sin abrir cada video)."""
    opts = base_ydl_opts(url, logger, verbose=False)
    opts["skip_download"] = True
    opts["extract_flat"] = "in_playlist"

    def work(ydl):
        return ydl.extract_info(url, download=False)

    info = _with_ydl(opts, logger, work)
    is_pl = _is_playlist(info)
    entries = (info.get("entries") or []) if is_pl else []
    if is_pl and not isinstance(entries, list):
        entries = list(entries)
    return {
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail") or "",
        "thumbnail_urls": collect_thumbnail_urls(info),
        "is_playlist": is_pl,
        "playlist_count": info.get("playlist_count") or len(entries),
        "url": url,
    }


# ============================================================
# AUTO-ACTUALIZACIÓN (modo desarrollo)
# ============================================================


def maybe_update_ytdlp_in_background(logger):
    """Intenta `pip install -U yt-dlp` en hilo separado (solo sin congelar)."""
    if is_frozen():
        return

    def _worker():
        try:
            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "yt-dlp[default,curl-cffi]"],
                capture_output=True,
                text=True,
                timeout=180,
                creationflags=no_window_flags(),
            )
            if r.returncode == 0:
                logger("✅ yt-dlp verificado/actualizado (se usa al reiniciar la app).")
            else:
                logger("⚠️ No se pudo actualizar yt-dlp: " + (r.stderr or "").strip()[:200])
        except Exception as e:
            logger(f"⚠️ Error al actualizar yt-dlp: {e}")

    threading.Thread(target=_worker, daemon=True).start()
