"""Todo lo que habla con yt-dlp: opciones, descarga, metadatos."""
import os
import shutil
import subprocess
import sys
import threading

from .config import META_YTDLP_IMPERSONATE, is_frozen
from .errors import ClipTimestampError, UserCancelledError
from .urls import _host_is_meta, _host_is_youtube, _url_hostname_lower
from .utils import format_duration, parse_time

def _merge_meta_impersonate_ytdlp_opts(url: str, ydl_opts: dict) -> dict:
    """Solo dominios Meta (Facebook, Instagram, …). Nunca YouTube."""
    if _host_is_meta(_url_hostname_lower(url)):
        # yt-dlp valida el parámetro 'impersonate' como ImpersonateTarget
        # (cuando el RequestHandler de curl_cffi está disponible).
        try:
            from yt_dlp.networking.impersonate import ImpersonateTarget

            ydl_opts["impersonate"] = ImpersonateTarget.from_str(META_YTDLP_IMPERSONATE)
        except Exception:
            # Fallback por compatibilidad (en algunas versiones acepta string)
            ydl_opts["impersonate"] = META_YTDLP_IMPERSONATE
    return ydl_opts


def _merge_youtube_opts(url: str, ydl_opts: dict) -> dict:
    """Configura opciones óptimas para YouTube (player_client y runtime JS)."""
    if _host_is_youtube(_url_hostname_lower(url)):
        if "extractor_args" not in ydl_opts:
            ydl_opts["extractor_args"] = {}
        if "youtube" not in ydl_opts["extractor_args"]:
            ydl_opts["extractor_args"]["youtube"] = {}
        if isinstance(ydl_opts["extractor_args"]["youtube"], dict):
            if "player_client" not in ydl_opts["extractor_args"]["youtube"]:
                ydl_opts["extractor_args"]["youtube"]["player_client"] = ["android", "web"]

        node_bin = shutil.which("node")
        if node_bin and "js_runtimes" not in ydl_opts:
            ydl_opts["js_runtimes"] = {"node": {"path": node_bin}}
    return ydl_opts


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


def maybe_update_ytdlp_in_background(logger):
    """Intenta `pip install -U yt-dlp` en hilo separado.

    Solo cuando NO estamos congelados (PyInstaller). En el .exe yt-dlp viaja
    embebido y pip no está disponible.
    """
    if is_frozen():
        return

    def _worker():
        try:
            creation = 0
            if sys.platform == "win32":
                creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            r = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    "--quiet",
                    "yt-dlp",
                ],
                capture_output=True,
                text=True,
                timeout=180,
                creationflags=creation,
            )
            if r.returncode == 0:
                logger("✅ yt-dlp verificado/actualizado.")
            else:
                logger(
                    "⚠️ No se pudo actualizar yt-dlp: "
                    + (r.stderr or "").strip()[:200]
                )
        except Exception as e:
            logger(f"⚠️ Error al actualizar yt-dlp: {e}")

    threading.Thread(target=_worker, daemon=True).start()


def _ydl_opts_metadata_only(url: str | None = None):
    opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if url:
        _merge_meta_impersonate_ytdlp_opts(url, opts)
        _merge_youtube_opts(url, opts)
    return opts


def make_ydl_progress_hook(cancel_event, pct_lo, pct_hi, emit):
    pct_lo = max(0, min(100, int(pct_lo)))
    pct_hi = max(0, min(100, int(pct_hi)))
    if pct_hi < pct_lo:
        pct_lo, pct_hi = pct_hi, pct_lo
    span = max(1, pct_hi - pct_lo)

    def hook(d):
        if cancel_event is not None and cancel_event.is_set():
            raise UserCancelledError("Cancelado por el usuario")
        if emit is None:
            return
        st = d.get("status")
        if st == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            speed = (d.get("_speed_str") or "").strip()
            if total and total > 0:
                sub = min(1.0, max(0.0, done / float(total)))
                p = int(pct_lo + sub * span)
                msg = f"Descargando {p}%"
                if speed:
                    msg += f" · {speed}"
                emit(min(p, pct_hi), msg)
            else:
                eta = (d.get("_eta_str") or "").strip()
                msg = "Descargando…"
                if eta:
                    msg += f" ETA {eta}"
                if speed:
                    msg += f" · {speed}"
                emit(pct_lo, msg)
        elif st == "postprocessing":
            emit(min(100, pct_hi), "Postproceso…")
        elif st == "finished":
            emit(pct_hi, "Descarga terminada")

    return hook


def aplicar_rangos_de_tiempo(ydl_opts, start_time, end_time, logger):
    start_sec = parse_time(start_time)
    end_sec = parse_time(end_time)

    if start_sec is not None or end_sec is not None:
        s = start_sec if start_sec is not None else 0
        e = end_sec if end_sec is not None else float("inf")

        _, download_range_func = _import_ytdlp()
        ydl_opts["download_ranges"] = download_range_func(None, [(s, e)])
        ydl_opts["force_keyframes_at_cuts"] = True

        texto_fin = e if e != float("inf") else "el final"
        logger(f"✂️ Fragmento configurado: de {s}s hasta {texto_fin}s (Corte por Keyframe)")

    return ydl_opts


def descargar_video_whatsapp(
    url,
    carpeta_salida,
    start_time=None,
    end_time=None,
    logger=print,
    cancel_event=None,
    emit_progress=None,
):
    """Descarga a archivo temporal %(id)s.src.* para luego exportar solo %(id)s.mp4."""
    logger("🎬 Iniciando descarga (modo WhatsApp) con yt-dlp…")
    os.makedirs(carpeta_salida, exist_ok=True)

    ydl_opts = {
        "outtmpl": os.path.join(carpeta_salida, "%(id)s.src.%(ext)s"),
        "restrictfilenames": True,
        "format": "bv*+ba/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
    }
    if cancel_event is not None or emit_progress is not None:
        ydl_opts["progress_hooks"] = [
            make_ydl_progress_hook(cancel_event, 0, 72, emit_progress)
        ]

    ydl_opts = aplicar_rangos_de_tiempo(ydl_opts, start_time, end_time, logger)
    _merge_meta_impersonate_ytdlp_opts(url, ydl_opts)
    _merge_youtube_opts(url, ydl_opts)

    YoutubeDL, _ = _import_ytdlp()
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
    except Exception as e:
        # Si esta build no tiene disponible curl_cffi/impersonation,
        # reintentamos sin 'impersonate' para evitar que falle toda la descarga.
        msg = str(e).lower()
        if ("impersonate target" in msg or "impersonate" in msg) and "impersonate" in ydl_opts:
            logger("⚠️ Impersonate no disponible en esta build; reintentando sin impersonate…")
            ydl_opts2 = dict(ydl_opts)
            ydl_opts2.pop("impersonate", None)
            with YoutubeDL(ydl_opts2) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
        else:
            raise

    base, _ = os.path.splitext(filename)
    mp4_candidate = base + ".mp4"
    final_path = mp4_candidate if os.path.exists(mp4_candidate) else filename
    logger(f"✅ Descarga terminada (WhatsApp base): {final_path}")
    return final_path, info


def descargar_video_car(
    url,
    carpeta_salida,
    start_time=None,
    end_time=None,
    logger=print,
    cancel_event=None,
    emit_progress=None,
):
    """Descarga a %(id)s.src.* (temporal). El nombre final lo elige el Worker (título + espacios)."""
    logger("🚗 Iniciando descarga (Modo Auto) con yt-dlp…")
    os.makedirs(carpeta_salida, exist_ok=True)

    ydl_opts = {
        "outtmpl": os.path.join(carpeta_salida, "%(id)s.src.%(ext)s"),
        "restrictfilenames": True,
        "format": "bv*[height<=720]+ba/best[height<=720]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
    }
    if cancel_event is not None or emit_progress is not None:
        ydl_opts["progress_hooks"] = [
            make_ydl_progress_hook(cancel_event, 0, 72, emit_progress)
        ]

    ydl_opts = aplicar_rangos_de_tiempo(ydl_opts, start_time, end_time, logger)
    _merge_meta_impersonate_ytdlp_opts(url, ydl_opts)
    _merge_youtube_opts(url, ydl_opts)

    YoutubeDL, _ = _import_ytdlp()
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
    except Exception as e:
        msg = str(e).lower()
        if ("impersonate target" in msg or "impersonate" in msg) and "impersonate" in ydl_opts:
            logger("⚠️ Impersonate no disponible en esta build; reintentando sin impersonate…")
            ydl_opts2 = dict(ydl_opts)
            ydl_opts2.pop("impersonate", None)
            with YoutubeDL(ydl_opts2) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
        else:
            raise

    base, _ = os.path.splitext(filename)
    mp4_candidate = base + ".mp4"
    final_path = mp4_candidate if os.path.exists(mp4_candidate) else filename
    logger(f"✅ Descarga terminada (Auto base): {final_path}")
    return final_path, info


def descargar_video_max_calidad(
    url,
    carpeta_salida,
    start_time=None,
    end_time=None,
    logger=print,
    cancel_event=None,
    emit_progress=None,
    max_height=None,
):
    logger("🎥 Iniciando descarga en máxima calidad con yt-dlp…")
    os.makedirs(carpeta_salida, exist_ok=True)

    if max_height:
        fmt = (
            f"bv*[height<={max_height}]+ba/bestvideo[height<={max_height}]+bestaudio/"
            f"best[height<={max_height}]/best"
        )
    else:
        fmt = "bv*+ba/bestvideo+bestaudio/best"

    ydl_opts = {
        "outtmpl": os.path.join(carpeta_salida, "%(title)s.%(ext)s"),
        "format": fmt,
        "merge_output_format": "mp4",
        "noplaylist": True,
    }
    if cancel_event is not None or emit_progress is not None:
        ydl_opts["progress_hooks"] = [
            make_ydl_progress_hook(cancel_event, 0, 95, emit_progress)
        ]

    ydl_opts = aplicar_rangos_de_tiempo(ydl_opts, start_time, end_time, logger)
    _merge_meta_impersonate_ytdlp_opts(url, ydl_opts)
    _merge_youtube_opts(url, ydl_opts)

    YoutubeDL, _ = _import_ytdlp()
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
    except Exception as e:
        msg = str(e).lower()
        if ("impersonate target" in msg or "impersonate" in msg) and "impersonate" in ydl_opts:
            logger("⚠️ Impersonate no disponible en esta build; reintentando sin impersonate…")
            ydl_opts2 = dict(ydl_opts)
            ydl_opts2.pop("impersonate", None)
            with YoutubeDL(ydl_opts2) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
        else:
            raise

    base, _ = os.path.splitext(filename)
    mp4_candidate = base + ".mp4"
    final_path = mp4_candidate if os.path.exists(mp4_candidate) else filename

    logger(f"✅ Descarga en máxima calidad terminada: {final_path}")
    return final_path


def descargar_video_directo(
    url,
    carpeta_salida,
    start_time=None,
    end_time=None,
    logger=print,
    cancel_event=None,
    emit_progress=None,
):
    logger("🎥 Iniciando descarga directa (720p SDR, sin recodificar) con yt-dlp…")
    os.makedirs(carpeta_salida, exist_ok=True)

    # Solo formato que tenga video+audio integrado, de hasta 720p, mp4
    fmt = "b[height<=720][ext=mp4]/b[ext=mp4]/b"

    ydl_opts = {
        "outtmpl": os.path.join(carpeta_salida, "%(title)s.%(ext)s"),
        "format": fmt,
        "noplaylist": True,
    }
    if cancel_event is not None or emit_progress is not None:
        ydl_opts["progress_hooks"] = [
            make_ydl_progress_hook(cancel_event, 0, 95, emit_progress)
        ]

    ydl_opts = aplicar_rangos_de_tiempo(ydl_opts, start_time, end_time, logger)
    _merge_meta_impersonate_ytdlp_opts(url, ydl_opts)
    _merge_youtube_opts(url, ydl_opts)

    YoutubeDL, _ = _import_ytdlp()
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
    except Exception as e:
        msg = str(e).lower()
        if ("impersonate target" in msg or "impersonate" in msg) and "impersonate" in ydl_opts:
            logger("⚠️ Impersonate no disponible en esta build; reintentando sin impersonate…")
            ydl_opts2 = dict(ydl_opts)
            ydl_opts2.pop("impersonate", None)
            with YoutubeDL(ydl_opts2) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
        else:
            raise

    logger(f"✅ Descarga directa terminada: {filename}")
    return filename


def descargar_audio_mp3(
    url,
    carpeta_salida,
    start_time=None,
    end_time=None,
    logger=print,
    cancel_event=None,
    emit_progress=None,
):
    logger("🎧 Iniciando descarga de solo audio (MP3) con metadatos + cover…")
    os.makedirs(carpeta_salida, exist_ok=True)

    ydl_opts = {
        "outtmpl": os.path.join(carpeta_salida, "%(title)s.%(ext)s"),
        "format": "bestaudio/best",
        "noplaylist": True,
        "writethumbnail": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            },
            {"key": "FFmpegMetadata"},
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg"},
            {"key": "EmbedThumbnail"},
        ],
    }
    if cancel_event is not None or emit_progress is not None:
        ydl_opts["progress_hooks"] = [
            make_ydl_progress_hook(cancel_event, 0, 92, emit_progress)
        ]

    ydl_opts = aplicar_rangos_de_tiempo(ydl_opts, start_time, end_time, logger)
    _merge_meta_impersonate_ytdlp_opts(url, ydl_opts)
    _merge_youtube_opts(url, ydl_opts)

    YoutubeDL, _ = _import_ytdlp()
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
    except Exception as e:
        msg = str(e).lower()
        if ("impersonate target" in msg or "impersonate" in msg) and "impersonate" in ydl_opts:
            logger("⚠️ Impersonate no disponible en esta build; reintentando sin impersonate…")
            ydl_opts2 = dict(ydl_opts)
            ydl_opts2.pop("impersonate", None)
            with YoutubeDL(ydl_opts2) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
        else:
            raise

    base, _ = os.path.splitext(filename)
    mp3_file = base + ".mp3"

    extra_suffixes = (
        ".webp",
        ".jpg",
        ".jpeg",
        ".png",
        ".m4a",
        ".webm",
        ".opus",
        ".ogg",
        ".aac",
        ".wav",
        ".flac",
        ".mkv",
        ".part",
    )
    posibles_sobrantes = {filename}
    for suf in extra_suffixes:
        posibles_sobrantes.add(base + suf)

    for f in posibles_sobrantes:
        if f.endswith(".mp3"):
            continue
        if os.path.exists(f):
            try:
                os.remove(f)
                logger(f"🧹 Borrado archivo sobrante: {f}")
            except OSError as e:
                logger(f"⚠️ No se pudo borrar {f}: {e}")

    logger(f"✅ Audio MP3 listo: {mp3_file}")
    return mp3_file


_CLIP_TIME_EPS = 1e-3


def clip_range_requested(start_time, end_time) -> bool:
    return parse_time(start_time) is not None or parse_time(end_time) is not None


def fetch_video_duration_seconds(url: str) -> float | None:
    YoutubeDL, _ = _import_ytdlp()
    ydl_opts = _ydl_opts_metadata_only(url)
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        msg = str(e).lower()
        if ("impersonate target" in msg or "impersonate" in msg) and "impersonate" in ydl_opts:
            # Si no hay impersonate disponible en el .exe, al menos intentamos metadatos sin esa huella.
            ydl_opts2 = dict(ydl_opts)
            ydl_opts2.pop("impersonate", None)
            with YoutubeDL(ydl_opts2) as ydl:
                info = ydl.extract_info(url, download=False)
        else:
            raise
    d = info.get("duration")
    if d is None:
        return None
    try:
        sec = float(d)
    except (TypeError, ValueError):
        return None
    if sec <= 0:
        return None
    return sec


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
