import os
import re
import sys
import time
import shutil
import subprocess
import threading
import urllib.request
from urllib.parse import urlparse

from PySide6.QtCore import (
    Qt,
    QObject,
    QThread,
    Signal,
    Slot,
    QSettings,
    QTimer,
    QUrl,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QTextEdit,
    QProgressBar,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QStackedWidget,
    QFrame,
    QToolButton,
    QSizePolicy,
    QSystemTrayIcon,
    QMenu,
    QSplashScreen,
)
from PySide6.QtGui import (
    QIcon,
    QImage,
    QPixmap,
    QDesktopServices,
    QAction,
    QGuiApplication,
)


# ============================================================
# CONSTANTS
# ============================================================

SETTINGS_ORG = "VibeLoader"
SETTINGS_APP = "VibeLoader"
APP_VERSION = "2.0"

# Cabeceras tipo navegador (YouTube / CDNs suelen bloquear User-Agent genérico de Python)
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# Facebook / Meta: workaround yt-dlp "Cannot parse data" (#15161) vía TLS impersonation.
META_YTDLP_IMPERSONATE = "chrome-99"


def _url_hostname_lower(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _host_is_youtube(hostname: str) -> bool:
    if not hostname:
        return False
    if hostname == "youtu.be":
        return True
    if hostname in ("music.youtube.com", "www.music.youtube.com"):
        return True
    if hostname == "youtube.com" or hostname.endswith(".youtube.com"):
        return True
    return False


def _host_is_meta(hostname: str) -> bool:
    if not hostname or _host_is_youtube(hostname):
        return False
    meta_suffixes = (
        "facebook.com",
        "fb.watch",
        "instagram.com",
        "threads.net",
    )
    for suf in meta_suffixes:
        if hostname == suf or hostname.endswith("." + suf):
            return True
    return False


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


def _referer_for_image_url(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return "https://www.youtube.com/"
    if "ytimg.com" in host or "ggpht.com" in host or "youtube.com" in host or "youtu.be" in host:
        return "https://www.youtube.com/"
    return f"https://{host}/"


def fetch_thumbnail_bytes(url: str, timeout: float = 12.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": BROWSER_UA,
            "Accept": "image/avif,image/webp,image/apng,image/png,image/jpeg,image/*,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Referer": _referer_for_image_url(url),
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def pixmap_from_image_bytes(data: bytes) -> QPixmap | None:
    if not data:
        return None
    img = QImage()
    if img.loadFromData(data):
        pix = QPixmap.fromImage(img)
        if not pix.isNull():
            return pix
    return None


def collect_thumbnail_urls(info: dict) -> list:
    """Ordena por resolución y devuelve URLs únicas (YouTube a veces solo sirve bien algunas)."""
    out = []
    thumbs = info.get("thumbnails") or []
    if thumbs:

        def area(t):
            return (t.get("height") or 0) * (t.get("width") or 0)

        for t in sorted(thumbs, key=area, reverse=True):
            u = t.get("url")
            if isinstance(u, str) and u.startswith("http") and u not in out:
                out.append(u)
    main = info.get("thumbnail")
    if isinstance(main, str) and main.startswith("http") and main not in out:
        out.insert(0, main)
    return out

PRESET_WHATSAPP = "WhatsApp 720p"
PRESET_MAX = "Máxima calidad (video)"
PRESET_MP3 = "Solo audio (MP3)"
PRESET_CAR = "Modo Auto (autoestéreo)"

ALL_PRESETS = (PRESET_WHATSAPP, PRESET_MAX, PRESET_MP3, PRESET_CAR)
ADVANCED_PRESETS = (PRESET_WHATSAPP, PRESET_MAX, PRESET_MP3, PRESET_CAR)

SETTINGS_KEYS = {
    PRESET_WHATSAPP: "dir_whatsapp",
    PRESET_MAX: "dir_video_hd",
    PRESET_MP3: "dir_mp3",
    PRESET_CAR: "dir_car",
}

LOG_FILE_PATH = None

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
SUPPORTED_HOSTS = (
    "youtube.com",
    "youtu.be",
    "music.youtube.com",
    "tiktok.com",
    "vm.tiktok.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "fb.watch",
    "twitch.tv",
    "soundcloud.com",
    "vimeo.com",
    "dailymotion.com",
)

FFMPEG_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.?\d*)")

FRIENDLY_ERRORS = (
    (
        "Sign in to confirm",
        "YouTube pide iniciar sesión para confirmar que no eres un bot. Espera unos minutos y vuelve a intentarlo.",
    ),
    ("Private video", "Este video es privado, no se puede descargar."),
    (
        "Video unavailable",
        "Este video no está disponible (puede haber sido eliminado o restringido por país).",
    ),
    (
        "HTTP Error 403",
        "El servidor rechazó la descarga (403). Probablemente yt-dlp necesita actualizarse.",
    ),
    (
        "HTTP Error 404",
        "Enlace no encontrado (404). Revisa que la URL esté correcta.",
    ),
    (
        "HTTP Error 429",
        "Muchas peticiones seguidas (429). Espera un par de minutos y vuelve a intentar.",
    ),
    (
        "Unable to extract",
        "yt-dlp no pudo leer este enlace. Probablemente necesita actualizarse.",
    ),
    (
        "Cannot parse data",
        "Facebook/Meta a veces devuelve una página que yt-dlp no puede leer. "
        "Actualiza yt-dlp (ideal nightly), instala el paquete curl-cffi, y para enlaces Meta "
        "esta app ya usa impersonación de navegador automáticamente.",
    ),
    (
        "Impersonate target",
        "La huella TLS del navegador no está disponible. "
        "En yt-dlp, `curl-cffi` suele necesitarse en la rama 0.14.x (no 0.15.x). "
        "Prueba: `pip install \"curl-cffi<0.15\"` y vuelve a intentarlo.",
    ),
    (
        "Unsupported URL",
        "Ese enlace no está soportado. Prueba con otro de YouTube u otro sitio.",
    ),
    (
        "ffmpeg",
        "No se encontró ffmpeg. Instálalo y agrégalo al PATH.",
    ),
    (
        "WinError 5",
        "Permiso denegado al guardar. Elige otra carpeta o cierra el archivo si lo tienes abierto.",
    ),
    (
        "No space left",
        "No hay espacio libre en el disco. Libera espacio y vuelve a intentar.",
    ),
    ("Cancelado", "Cancelaste la descarga."),
)

THEMES = {
    "dark": {
        "bg": "#15161c",
        "surface": "#1d1f29",
        "border": "#2c2f3d",
        "text": "#f4f5fb",
        "text_dim": "#a4abc2",
        "accent": "#7c83ff",
        "accent_hover": "#969cff",
        "music": "#7c83ff",
        "music_hover": "#969cff",
        "video": "#22c1c3",
        "video_hover": "#44d4d6",
        "car": "#ffb454",
        "car_hover": "#ffc274",
        "success": "#4ade80",
        "error": "#fb7185",
        "title": "#ffeaa7",
    },
    "light": {
        "bg": "#fafbff",
        "surface": "#ffffff",
        "border": "#e1e4ee",
        "text": "#1d1f29",
        "text_dim": "#5b6479",
        "accent": "#5a64f0",
        "accent_hover": "#7079f4",
        "music": "#5a64f0",
        "music_hover": "#7079f4",
        "video": "#0ca7a8",
        "video_hover": "#1ec0c1",
        "car": "#e08e2a",
        "car_hover": "#eda43d",
        "success": "#16a34a",
        "error": "#dc2626",
        "title": "#1d1f29",
    },
}


# ============================================================
# HELPERS GENERALES
# ============================================================


def ensure_log_path():
    global LOG_FILE_PATH
    if LOG_FILE_PATH:
        return LOG_FILE_PATH
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    log_dir = os.path.join(base, "VibeLoader")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        log_dir = base
    LOG_FILE_PATH = os.path.join(log_dir, "vibeload.log")
    return LOG_FILE_PATH


def append_log_file(line: str):
    try:
        with open(ensure_log_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def resource_path(relative_name: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_name)
    return os.path.join(os.path.dirname(__file__), relative_name)


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


def check_tool(tool_name):
    return shutil.which(tool_name) is not None


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def parse_time(t_str):
    """Convierte 'MM:SS', 'HH:MM:SS', segundos solos, '90s', '1m30s', '2m' a segundos."""
    if not t_str or not t_str.strip():
        return None
    s = t_str.strip().lower().replace(",", ".")
    try:
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*s", s)
        if m:
            return float(m.group(1))
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*m(?:\s*(\d+(?:\.\d+)?)\s*s)?", s)
        if m:
            return float(m.group(1)) * 60.0 + float(m.group(2) or 0)
        parts = [float(p) for p in s.split(":")]
        if len(parts) == 1:
            return parts[0]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except ValueError:
        return None
    return None


def format_duration(seconds) -> str:
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    if s < 0:
        return ""
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def find_url_in_text(text: str):
    if not text:
        return None
    m = URL_RE.search(text)
    return m.group(0) if m else None


def looks_like_supported_url(url: str) -> bool:
    if not url:
        return False
    u = url.lower().strip()
    if not (u.startswith("http://") or u.startswith("https://")):
        return False
    return any(h in u for h in SUPPORTED_HOSTS)


def friendly(msg: str) -> str:
    if not msg:
        return "Algo salió mal."
    low = msg.lower()
    for needle, friendly_msg in FRIENDLY_ERRORS:
        if needle.lower() in low:
            return friendly_msg
    return msg.strip().split("\n")[0][:300]


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


# ============================================================
# SETTINGS
# ============================================================


def suggested_default_dirs():
    home = os.path.expanduser("~")
    videos = os.path.join(home, "Videos")
    base = videos if os.path.isdir(videos) else home
    music = os.path.join(home, "Music")
    music_dir = music if os.path.isdir(music) else base
    return {
        PRESET_WHATSAPP: os.path.join(base, "VibeLoader", "WhatsApp"),
        PRESET_MAX: os.path.join(base, "VibeLoader", "HD"),
        PRESET_MP3: music_dir,
        PRESET_CAR: os.path.join(base, "VibeLoader", "Auto"),
    }


def load_default_dirs_from_settings(settings: QSettings):
    if not settings.value("defaults_configured", False, type=bool):
        return None
    out = {}
    for preset, key in SETTINGS_KEYS.items():
        out[preset] = str(settings.value(key) or "").strip()
    if not all(out.get(p) for p in (PRESET_WHATSAPP, PRESET_MAX, PRESET_MP3)):
        return None
    if not out.get(PRESET_CAR):
        out[PRESET_CAR] = suggested_default_dirs()[PRESET_CAR]
    return out


def save_default_dirs_to_settings(settings: QSettings, dirs: dict):
    settings.setValue("defaults_configured", True)
    for preset, key in SETTINGS_KEYS.items():
        if dirs.get(preset):
            settings.setValue(key, dirs[preset])


def load_recent_urls(settings: QSettings, limit: int = 5):
    raw = settings.value("recent_urls", [])
    if isinstance(raw, str):
        raw = [raw] if raw else []
    if not isinstance(raw, list):
        raw = []
    out = []
    for u in raw:
        s = str(u).strip()
        if s and s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def save_recent_urls(settings: QSettings, urls):
    settings.setValue("recent_urls", list(urls))


# ============================================================
# DESCARGA / CONVERSIÓN (CORE)
# ============================================================


class UserCancelledError(Exception):
    """El usuario canceló la descarga o la conversión."""


class ClipTimestampError(Exception):
    """Marcas de tiempo de recorte fuera del rango del video."""


def _ydl_opts_metadata_only(url: str | None = None):
    opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if url:
        _merge_meta_impersonate_ytdlp_opts(url, opts)
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


def _run_ffmpeg_recompress(
    src,
    dst,
    logger,
    emit_progress,
    cancel_event,
    proc_holder,
    pct_lo,
    pct_hi,
    *,
    profile,
    level,
    max_w,
    max_h,
    fps,
    crf,
    preset_speed,
    audio_b,
    audio_ar,
    nice_name,
):
    logger(f"🎬 Recompresión con ffmpeg ({nice_name})…")
    duration = ffprobe_duration_seconds(src)

    vf = (
        f"scale='min({max_w},iw)':'min({max_h},ih)':force_original_aspect_ratio=decrease,"
        f"scale=trunc(iw/2)*2:trunc(ih/2)*2"
    )
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
        vf,
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-profile:v",
        profile,
        "-level",
        level,
        "-pix_fmt",
        "yuv420p",
        "-crf",
        str(crf),
        "-preset",
        preset_speed,
        "-c:a",
        "aac",
        "-b:a",
        audio_b,
        "-ar",
        str(audio_ar),
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        dst,
    ]

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


def run_ffmpeg_whatsapp(
    src, dst, logger, emit_progress, cancel_event, proc_holder, pct_lo, pct_hi
):
    """H.264 Main@L4.0, máx 1280x720, 30 fps, AAC LC 128k, +faststart."""
    return _run_ffmpeg_recompress(
        src,
        dst,
        logger,
        emit_progress,
        cancel_event,
        proc_holder,
        pct_lo,
        pct_hi,
        profile="main",
        level="4.0",
        max_w=1280,
        max_h=720,
        fps=30,
        crf=23,
        preset_speed="medium",
        audio_b="128k",
        audio_ar=48000,
        nice_name="WhatsApp / móviles",
    )


def run_ffmpeg_car(
    src, dst, logger, emit_progress, cancel_event, proc_holder, pct_lo, pct_hi
):
    """H.264 Baseline@L3.1, máx 1280x720, 30 fps, AAC LC 128k 44.1 kHz, +faststart.

    Profile Baseline + level 3.1 dan máxima compatibilidad con autoestéreos y
    reproductores antiguos (sin B-frames, sin CABAC).
    """
    return _run_ffmpeg_recompress(
        src,
        dst,
        logger,
        emit_progress,
        cancel_event,
        proc_holder,
        pct_lo,
        pct_hi,
        profile="baseline",
        level="3.1",
        max_w=1280,
        max_h=720,
        fps=30,
        crf=22,
        preset_speed="medium",
        audio_b="128k",
        audio_ar=44100,
        nice_name="Modo Auto (autoestéreo)",
    )


def windows_safe_video_name(name: str, max_len: int = 180) -> str:
    """Nombre de archivo seguro en Windows, conservando espacios (sin guiones bajos forzados)."""
    if not name or not str(name).strip():
        return "video"
    s = str(name).replace("\r", " ").replace("\n", " ").strip()
    for c in '<>:"/\\|?*':
        s = s.replace(c, "")
    s = re.sub(r"\s+", " ", s).strip(" .")
    if len(s) > max_len:
        s = s[:max_len].rstrip(" .")
    return s or "video"


def aplicar_rangos_de_tiempo(ydl_opts, start_time, end_time, logger):
    start_sec = parse_time(start_time)
    end_sec = parse_time(end_time)

    if start_sec is not None or end_sec is not None:
        s = start_sec if start_sec is not None else 0
        e = end_sec if end_sec is not None else float("inf")

        _, download_range_func = _import_ytdlp()
        ydl_opts["download_ranges"] = download_range_func(None, [(s, e)])

        if "extractor_args" not in ydl_opts:
            ydl_opts["extractor_args"] = {}
        ydl_opts["extractor_args"]["youtube"] = [
            "player_client=default,-android_sdkless"
        ]

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


def pick_auto_output_path(folder: str, title: str, video_id: str, input_path: str) -> str:
    """Salida Modo Auto: «Título del video.mp4» con espacios; si ya existe otro archivo con ese nombre, «Título [id].mp4»."""
    safe = windows_safe_video_name(title, max_len=160)
    candidate = os.path.join(folder, safe + ".mp4")
    in_abs = os.path.abspath(input_path)
    if not os.path.exists(candidate):
        return candidate
    if os.path.abspath(candidate) == in_abs:
        return candidate
    return os.path.join(
        folder, windows_safe_video_name(f"{title} [{video_id}]", max_len=160) + ".mp4"
    )


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


# ============================================================
# WORKER DE DESCARGA
# ============================================================


class Worker(QObject):
    finished = Signal()
    error = Signal(str)
    log = Signal(str)
    progress = Signal(int, str)
    completed = Signal(str)

    def __init__(self, url, carpeta_salida, preset, start_time, end_time):
        super().__init__()
        self.url = url
        self.carpeta_salida = carpeta_salida
        self.preset = preset
        self.start_time = start_time
        self.end_time = end_time
        self._cancel_event = threading.Event()
        self._proc_holder = {}

    @Slot()
    def request_cancel(self):
        self._cancel_event.set()
        proc = self._proc_holder.get("p")
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    @Slot()
    def run(self):
        result_path = None
        try:
            def logger(msg):
                self.log.emit(msg)

            def emit_progress(p, msg):
                self.progress.emit(max(0, min(100, int(p))), msg)

            logger("🌐 URL: " + self.url)
            logger("📁 Carpeta: " + self.carpeta_salida)
            logger(f"🎚 Modo: {self.preset}")
            emit_progress(0, "Iniciando…")

            if clip_range_requested(self.start_time, self.end_time):
                duration = fetch_video_duration_seconds(self.url)
                if duration is None:
                    raise ClipTimestampError(
                        "No se pudo obtener la duración del video (puede ser una transmisión en "
                        "vivo o el sitio no publica esa información). No se puede recortar por "
                        "tiempo sin conocer la duración."
                    )
                validate_clip_against_duration(
                    self.start_time, self.end_time, duration
                )

            if self.preset == PRESET_WHATSAPP:
                input_file, info = descargar_video_whatsapp(
                    self.url,
                    self.carpeta_salida,
                    self.start_time,
                    self.end_time,
                    logger=logger,
                    cancel_event=self._cancel_event,
                    emit_progress=emit_progress,
                )
                vid = str(info.get("id") or "video").strip()
                output_file = os.path.join(self.carpeta_salida, f"{vid}.mp4")
                run_ffmpeg_whatsapp(
                    input_file,
                    output_file,
                    logger,
                    emit_progress,
                    self._cancel_event,
                    self._proc_holder,
                    73,
                    99,
                )
                _safe_remove(input_file, logger)
                result_path = output_file
                logger("✨ Listo. Compatible con WhatsApp.")
                emit_progress(100, "Listo")

            elif self.preset == PRESET_CAR:
                input_file, info = descargar_video_car(
                    self.url,
                    self.carpeta_salida,
                    self.start_time,
                    self.end_time,
                    logger=logger,
                    cancel_event=self._cancel_event,
                    emit_progress=emit_progress,
                )
                title = (info.get("title") or "video").strip()
                vid = str(info.get("id") or "unknown").strip()
                output_file = pick_auto_output_path(
                    self.carpeta_salida, title, vid, input_file
                )
                run_ffmpeg_car(
                    input_file,
                    output_file,
                    logger,
                    emit_progress,
                    self._cancel_event,
                    self._proc_holder,
                    73,
                    99,
                )
                _safe_remove(input_file, logger)
                result_path = output_file
                logger("✨ Listo. Compatible con autoestéreos.")
                emit_progress(100, "Listo")

            elif self.preset == PRESET_MAX:
                fname = descargar_video_max_calidad(
                    self.url,
                    self.carpeta_salida,
                    self.start_time,
                    self.end_time,
                    logger=logger,
                    cancel_event=self._cancel_event,
                    emit_progress=emit_progress,
                )
                result_path = fname
                emit_progress(100, "Listo")
                logger("✨ Listo. Video descargado en la mejor calidad.")

            elif self.preset == PRESET_MP3:
                fname = descargar_audio_mp3(
                    self.url,
                    self.carpeta_salida,
                    self.start_time,
                    self.end_time,
                    logger=logger,
                    cancel_event=self._cancel_event,
                    emit_progress=emit_progress,
                )
                result_path = fname
                emit_progress(100, "Listo")
                logger("✨ Listo. Audio MP3 listo.")

            else:
                raise ValueError(f"Preset no reconocido: {self.preset}")

            if result_path:
                self.completed.emit(result_path)

        except UserCancelledError as e:
            self.log.emit("⏹️ " + str(e))
            self.progress.emit(0, "Cancelado")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


def _safe_remove(path, logger):
    try:
        if os.path.exists(path):
            os.remove(path)
            logger(f"🧹 Archivo intermedio borrado: {path}")
    except OSError as e:
        logger(f"⚠️ No se pudo borrar {path}: {e}")


# ============================================================
# METADATA FETCHER
# ============================================================


class MetadataFetcher(QObject):
    """Vive en su propio QThread; extrae info sin descargar."""

    fetched = Signal(dict, int)
    failed = Signal(str, int)

    @Slot(str, int)
    def fetch(self, url: str, token: int):
        if not url:
            return
        try:
            YoutubeDL, _ = _import_ytdlp()
            ydl_opts = _ydl_opts_metadata_only(url)
            try:
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
            except Exception as e:
                msg = str(e).lower()
                if ("impersonate target" in msg or "impersonate" in msg) and "impersonate" in ydl_opts:
                    self.log.emit("⚠️ Impersonate no disponible en esta build; reintentando sin impersonate…")
                    ydl_opts2 = dict(ydl_opts)
                    ydl_opts2.pop("impersonate", None)
                    with YoutubeDL(ydl_opts2) as ydl:
                        info = ydl.extract_info(url, download=False)
                else:
                    raise
        except Exception as e:
            self.failed.emit(str(e), token)
            return
        data = {
            "title": info.get("title") or "",
            "channel": info.get("channel") or info.get("uploader") or "",
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail") or "",
            "thumbnail_urls": collect_thumbnail_urls(info),
            "url": url,
        }
        self.fetched.emit(data, token)


# ============================================================
# DIÁLOGO DE CARPETAS PREDETERMINADAS
# ============================================================


class DefaultFoldersConfigDialog(QDialog):
    ROWS = (
        (PRESET_WHATSAPP, "Videos para WhatsApp:"),
        (PRESET_MAX, "Videos en máxima calidad:"),
        (PRESET_MP3, "Música / MP3:"),
        (PRESET_CAR, "Videos para Modo Auto (autoestéreo):"),
    )

    def __init__(self, parent, paths: dict, first_run: bool = False):
        super().__init__(parent)
        self._edits = {}
        self.setWindowTitle(
            "Bienvenida — carpetas predeterminadas"
            if first_run
            else "Carpetas predeterminadas"
        )
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        if first_run:
            intro = QLabel(
                "Es la primera vez que abres VibeLoader. Elige dónde guardar "
                "los archivos de cada modo (puedes cambiarlo después)."
            )
            intro.setWordWrap(True)
            layout.addWidget(intro)

        for key, label_text in self.ROWS:
            layout.addWidget(QLabel(label_text))
            row = QHBoxLayout()
            edit = QLineEdit()
            edit.setText(paths.get(key, ""))
            browse = QPushButton("Examinar…")
            browse.clicked.connect(lambda _=False, e=edit: self._browse_folder(e))
            row.addWidget(edit)
            row.addWidget(browse)
            layout.addLayout(row)
            self._edits[key] = edit

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_folder(self, edit: QLineEdit):
        start = edit.text().strip() or os.path.expanduser("~")
        carpeta = QFileDialog.getExistingDirectory(self, "Elegir carpeta", start)
        if carpeta:
            edit.setText(carpeta)

    def _try_accept(self):
        for key, edit in self._edits.items():
            if not edit.text().strip():
                QMessageBox.warning(
                    self, "Falta una ruta", f"Indica una carpeta válida para «{key}»."
                )
                return
        self.accept()

    def get_paths(self) -> dict:
        return {k: e.text().strip() for k, e in self._edits.items()}


# ============================================================
# STYLESHEET (TEMA)
# ============================================================


def build_stylesheet(theme_name: str) -> str:
    t = THEMES.get(theme_name, THEMES["dark"])
    return f"""
        QWidget {{
            background-color: {t['bg']};
            color: {t['text']};
            font-family: "Segoe UI Variable", "Segoe UI", system-ui, Arial, sans-serif;
            font-size: 11pt;
        }}
        QMainWindow {{
            background-color: {t['bg']};
        }}
        QLineEdit, QTextEdit, QComboBox {{
            background-color: {t['surface']};
            color: {t['text']};
            border: 1px solid {t['border']};
            border-radius: 8px;
            padding: 8px 10px;
            selection-background-color: {t['accent']};
        }}
        QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
            border: 1px solid {t['accent']};
        }}
        QPushButton {{
            background-color: {t['accent']};
            color: white;
            border: none;
            border-radius: 10px;
            padding: 8px 14px;
            font-weight: 600;
        }}
        QPushButton:hover {{ background-color: {t['accent_hover']}; }}
        QPushButton:disabled {{ background-color: {t['border']}; color: {t['text_dim']}; }}
        QPushButton#secondary {{
            background-color: transparent;
            color: {t['text']};
            border: 1px solid {t['border']};
        }}
        QPushButton#secondary:hover {{
            border: 1px solid {t['accent']};
            color: {t['accent']};
        }}
        QPushButton#big_music {{ background-color: {t['music']}; min-height: 64px; font-size: 13pt; }}
        QPushButton#big_music:hover {{ background-color: {t['music_hover']}; }}
        QPushButton#big_video {{ background-color: {t['video']}; min-height: 64px; font-size: 13pt; }}
        QPushButton#big_video:hover {{ background-color: {t['video_hover']}; }}
        QPushButton#big_car {{ background-color: {t['car']}; min-height: 64px; font-size: 13pt; }}
        QPushButton#big_car:hover {{ background-color: {t['car_hover']}; }}
        QProgressBar {{
            background-color: {t['surface']};
            color: {t['text']};
            border: 1px solid {t['border']};
            border-radius: 8px;
            text-align: center;
            min-height: 26px;
            font-weight: 600;
        }}
        QProgressBar::chunk {{
            background-color: {t['video']};
            border-radius: 8px;
        }}
        QFrame#card_success {{
            background-color: {t['surface']};
            border: 1px solid {t['success']};
            border-radius: 10px;
        }}
        QFrame#card_error {{
            background-color: {t['surface']};
            border: 1px solid {t['error']};
            border-radius: 10px;
        }}
        QFrame#preview {{
            background-color: {t['surface']};
            border: 1px solid {t['border']};
            border-radius: 10px;
        }}
        QLabel#TitleLabel {{
            font-size: 22pt;
            font-weight: 700;
            color: {t['title']};
        }}
        QLabel#SubtitleLabel {{
            font-size: 10pt;
            color: {t['text_dim']};
        }}
        QLabel#PreviewTitle {{
            font-size: 12pt;
            font-weight: 600;
            color: {t['text']};
        }}
        QLabel#PreviewMeta {{
            font-size: 10pt;
            color: {t['text_dim']};
        }}
        QLabel#FolderHint {{
            font-size: 9pt;
            color: {t['text_dim']};
        }}
        QLineEdit#bigUrl {{
            font-size: 13pt;
            padding: 14px 16px;
            min-height: 28px;
        }}
        QToolButton {{
            background: transparent;
            color: {t['text']};
            border: 1px solid {t['border']};
            border-radius: 8px;
            padding: 6px 10px;
        }}
        QToolButton:hover {{
            border: 1px solid {t['accent']};
            color: {t['accent']};
        }}
        QToolButton::menu-indicator {{ width: 0px; image: none; }}
    """


# ============================================================
# VISTA SIMPLE (modo papá)
# ============================================================


class SimpleView(QWidget):
    """Pegar enlace -> elegir Música / Video / Auto -> descargar."""

    request_fetch_metadata = Signal(str, int)
    request_open_advanced = Signal()
    request_open_folders = Signal()
    request_toggle_theme = Signal()
    request_start = Signal(str, str)
    request_cancel = Signal()
    _thumbnail_loaded = Signal(QPixmap, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._token = 0
        self._last_url = ""
        self._last_result_path = None
        self._is_busy = False
        self._fetch_timer = QTimer(self)
        self._fetch_timer.setSingleShot(True)
        self._fetch_timer.setInterval(450)
        self._fetch_timer.timeout.connect(self._trigger_fetch)
        self._thumbnail_loaded.connect(self._on_thumbnail_loaded)
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)

        # Top bar
        top = QHBoxLayout()
        title = QLabel("VibeLoader")
        title.setObjectName("TitleLabel")
        top.addWidget(title)
        top.addStretch()
        self.theme_btn = QToolButton()
        self.theme_btn.setText("Tema")
        self.theme_btn.setToolTip("Cambiar entre claro y oscuro")
        self.theme_btn.clicked.connect(self.request_toggle_theme)
        top.addWidget(self.theme_btn)
        self.advanced_btn = QToolButton()
        self.advanced_btn.setText("Modo avanzado")
        self.advanced_btn.clicked.connect(self.request_open_advanced)
        top.addWidget(self.advanced_btn)
        layout.addLayout(top)

        sub = QLabel("Pega el enlace y elige cómo descargar.")
        sub.setObjectName("SubtitleLabel")
        layout.addWidget(sub)

        # URL row
        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("bigUrl")
        self.url_edit.setPlaceholderText("Pega aquí el enlace de YouTube")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.textChanged.connect(self._on_url_changed)
        url_row.addWidget(self.url_edit, 1)

        self.paste_btn = QPushButton("Pegar")
        self.paste_btn.setObjectName("secondary")
        self.paste_btn.clicked.connect(self._do_paste)
        url_row.addWidget(self.paste_btn)

        self.recents_btn = QToolButton()
        self.recents_btn.setText("Recientes")
        self.recents_btn.setToolTip("Últimos enlaces usados")
        self.recents_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._recents_menu = QMenu(self)
        self.recents_btn.setMenu(self._recents_menu)
        self.recents_btn.setEnabled(False)
        url_row.addWidget(self.recents_btn)

        layout.addLayout(url_row)

        # Preview
        self.preview = QFrame()
        self.preview.setObjectName("preview")
        self.preview.setVisible(False)
        prev_layout = QHBoxLayout(self.preview)
        prev_layout.setContentsMargins(10, 10, 10, 10)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(160, 90)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet(
            "background: transparent; border: 1px solid rgba(127,127,127,0.25); border-radius: 6px;"
        )
        prev_layout.addWidget(self.thumb_label)

        text_col = QVBoxLayout()
        self.preview_title = QLabel("Cargando…")
        self.preview_title.setObjectName("PreviewTitle")
        self.preview_title.setWordWrap(True)
        self.preview_meta = QLabel("")
        self.preview_meta.setObjectName("PreviewMeta")
        text_col.addWidget(self.preview_title)
        text_col.addWidget(self.preview_meta)
        text_col.addStretch()
        prev_layout.addLayout(text_col, 1)
        layout.addWidget(self.preview)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.btn_music = QPushButton("Descargar Música\n(MP3)")
        self.btn_music.setObjectName("big_music")
        self.btn_music.clicked.connect(lambda: self._start(PRESET_MP3))

        self.btn_video = QPushButton("Descargar Video\n(hasta 1080p)")
        self.btn_video.setObjectName("big_video")
        self.btn_video.clicked.connect(lambda: self._start(PRESET_MAX))

        self.btn_car = QPushButton("Modo Auto\n(autoestéreo)")
        self.btn_car.setObjectName("big_car")
        self.btn_car.setToolTip(
            "Descarga y reconvierte a un MP4 en 720p compatible con autoestéreos"
        )
        self.btn_car.clicked.connect(lambda: self._start(PRESET_CAR))

        for b in (self.btn_music, self.btn_video, self.btn_car):
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        # Folder hint
        folder_row = QHBoxLayout()
        self.folder_hint = QLabel("")
        self.folder_hint.setObjectName("FolderHint")
        folder_row.addWidget(self.folder_hint, 1)
        self.change_folder_btn = QPushButton("Cambiar carpetas…")
        self.change_folder_btn.setObjectName("secondary")
        self.change_folder_btn.clicked.connect(self.request_open_folders)
        folder_row.addWidget(self.change_folder_btn)
        layout.addLayout(folder_row)

        # Progress + cancel
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Esperando…")
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setObjectName("secondary")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.request_cancel)
        cancel_row = QHBoxLayout()
        cancel_row.addStretch()
        cancel_row.addWidget(self.cancel_btn)
        layout.addLayout(cancel_row)

        # Result card
        self.result_card = QFrame()
        self.result_card.setObjectName("card_success")
        self.result_card.setVisible(False)
        rl = QVBoxLayout(self.result_card)
        rl.setContentsMargins(12, 10, 12, 10)
        self.result_text = QLabel("")
        self.result_text.setWordWrap(True)
        rl.addWidget(self.result_text)
        rb = QHBoxLayout()
        self.open_folder_btn = QPushButton("Abrir carpeta")
        self.open_folder_btn.clicked.connect(self._open_result_folder)
        self.open_file_btn = QPushButton("Abrir archivo")
        self.open_file_btn.setObjectName("secondary")
        self.open_file_btn.clicked.connect(self._open_result_file)
        self.again_btn = QPushButton("Otra descarga")
        self.again_btn.setObjectName("secondary")
        self.again_btn.clicked.connect(self._reset_for_new_download)
        rb.addWidget(self.open_folder_btn)
        rb.addWidget(self.open_file_btn)
        rb.addWidget(self.again_btn)
        rb.addStretch()
        rl.addLayout(rb)
        layout.addWidget(self.result_card)

        # Error card
        self.error_card = QFrame()
        self.error_card.setObjectName("card_error")
        self.error_card.setVisible(False)
        el = QVBoxLayout(self.error_card)
        el.setContentsMargins(12, 10, 12, 10)
        self.error_text = QLabel("")
        self.error_text.setWordWrap(True)
        el.addWidget(self.error_text)
        eb = QHBoxLayout()
        self.retry_btn = QPushButton("Reintentar")
        self.retry_btn.setObjectName("secondary")
        self.retry_btn.clicked.connect(self._on_retry)
        self.dismiss_btn = QPushButton("Cerrar aviso")
        self.dismiss_btn.setObjectName("secondary")
        self.dismiss_btn.clicked.connect(lambda: self.error_card.setVisible(False))
        eb.addWidget(self.retry_btn)
        eb.addWidget(self.dismiss_btn)
        eb.addStretch()
        el.addLayout(eb)
        layout.addWidget(self.error_card)

        layout.addStretch()

    # ---------- Public API ----------
    def set_busy(self, busy: bool):
        self._is_busy = busy
        for b in (
            self.btn_music,
            self.btn_video,
            self.btn_car,
            self.url_edit,
            self.paste_btn,
            self.change_folder_btn,
            self.recents_btn,
            self.advanced_btn,
        ):
            b.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.cancel_btn.setVisible(busy)
        if busy:
            self.result_card.setVisible(False)
            self.error_card.setVisible(False)
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat("Iniciando…")

    def set_progress(self, pct: int, detail: str):
        if not self._is_busy:
            return
        self.progress.setRange(0, 100)
        self.progress.setValue(pct)
        self.progress.setFormat(detail or f"{pct}%")

    def show_success(self, file_path: str):
        self._last_result_path = file_path
        if file_path:
            short = file_path
            try:
                short = os.path.basename(file_path)
            except Exception:
                pass
            self.result_text.setText(
                f"Listo. Tu archivo:\n<b>{short}</b><br>"
                f"<span style='color:#888;'>Carpeta: {os.path.dirname(file_path)}</span>"
            )
            self.result_text.setTextFormat(Qt.TextFormat.RichText)
        else:
            self.result_text.setText("Listo.")
        self.result_card.setVisible(True)
        self.error_card.setVisible(False)

    def show_error(self, msg: str):
        self.error_text.setText(f"⚠ {friendly(msg)}")
        self.error_card.setVisible(True)
        self.result_card.setVisible(False)

    def show_cancelled(self):
        self.error_text.setText("Descarga cancelada.")
        self.error_card.setVisible(True)
        self.result_card.setVisible(False)

    def update_folder_hint(self, dirs: dict):
        parts = []
        if dirs.get(PRESET_MP3):
            parts.append(f"Música → {os.path.basename(dirs[PRESET_MP3])}")
        if dirs.get(PRESET_MAX):
            parts.append(f"Video → {os.path.basename(dirs[PRESET_MAX])}")
        if dirs.get(PRESET_CAR):
            parts.append(f"Auto → {os.path.basename(dirs[PRESET_CAR])}")
        self.folder_hint.setText("Se guardará en: " + " · ".join(parts) if parts else "")

    def set_recents(self, urls):
        self._recents_menu.clear()
        if not urls:
            self.recents_btn.setEnabled(False)
            return
        self.recents_btn.setEnabled(True)
        for u in urls:
            label = u if len(u) <= 70 else u[:67] + "…"
            act = QAction(label, self._recents_menu)
            act.triggered.connect(lambda _=False, x=u: self._use_recent(x))
            self._recents_menu.addAction(act)

    def maybe_autopaste_clipboard(self):
        if self._is_busy:
            return
        if self.url_edit.text().strip():
            return
        clip = QGuiApplication.clipboard()
        if clip is None:
            return
        text = clip.text() or ""
        url = find_url_in_text(text)
        if url and looks_like_supported_url(url):
            self.url_edit.setText(url)

    @Slot(dict, int)
    def on_metadata(self, data, token):
        if token != self._token:
            return
        if data.get("url") != self._last_url:
            return
        self.preview_title.setText(data.get("title") or "(sin título)")
        meta = []
        if data.get("channel"):
            meta.append(data["channel"])
        d = format_duration(data.get("duration"))
        if d:
            meta.append(d)
        self.preview_meta.setText(" · ".join(meta))
        urls = data.get("thumbnail_urls") or []
        if not urls and data.get("thumbnail"):
            urls = [data["thumbnail"]]
        if urls:
            self._load_thumbnail_async(urls, token)

    @Slot(QPixmap, int)
    def _on_thumbnail_loaded(self, pix: QPixmap, token: int):
        if token != self._token:
            return
        if pix.isNull():
            return
        self.thumb_label.setPixmap(pix)

    @Slot(str, int)
    def on_metadata_failed(self, msg, token):
        if token != self._token:
            return
        self.preview.setVisible(False)

    # ---------- Internal ----------
    def _on_url_changed(self, text: str):
        self.preview.setVisible(False)
        self.error_card.setVisible(False)
        self.result_card.setVisible(False)
        url = text.strip()
        if looks_like_supported_url(url):
            self._last_url = url
            self._fetch_timer.start()
        else:
            self._fetch_timer.stop()

    def _trigger_fetch(self):
        if not self._last_url:
            return
        self._token += 1
        self.thumb_label.clear()
        self.preview_title.setText("Cargando información…")
        self.preview_meta.setText("")
        self.preview.setVisible(True)
        self.request_fetch_metadata.emit(self._last_url, self._token)

    def _load_thumbnail_async(self, urls, token: int):
        """Descarga miniatura en hilo aparte; aplica pixmap en hilo GUI vía señal."""
        if isinstance(urls, str):
            urls = [urls] if urls else []
        if not urls:
            return
        my_token = token
        urls_copy = list(urls)

        def _fetch():
            scaled = None
            for url in urls_copy:
                if my_token != self._token:
                    return
                try:
                    raw = fetch_thumbnail_bytes(url)
                except Exception:
                    continue
                pix = pixmap_from_image_bytes(raw)
                if pix is None or pix.isNull():
                    continue
                scaled = pix.scaled(
                    160,
                    90,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                break
            if scaled is not None and not scaled.isNull():
                self._thumbnail_loaded.emit(scaled, my_token)

        threading.Thread(target=_fetch, daemon=True).start()

    def _do_paste(self):
        clip = QGuiApplication.clipboard()
        if clip is None:
            return
        text = clip.text() or ""
        url = find_url_in_text(text) or text.strip()
        if url:
            self.url_edit.setText(url)
            self.url_edit.setFocus()

    def _use_recent(self, url: str):
        self.url_edit.setText(url)

    def _start(self, preset: str):
        url = self.url_edit.text().strip()
        if not url:
            self.show_error("Pega un enlace antes de descargar.")
            return
        if not looks_like_supported_url(url):
            self.show_error(
                "Ese enlace no se ve válido. Asegúrate de copiar uno de YouTube u otro sitio compatible."
            )
            return
        self.error_card.setVisible(False)
        self.result_card.setVisible(False)
        self.request_start.emit(url, preset)

    def _reset_for_new_download(self):
        self.url_edit.clear()
        self.preview.setVisible(False)
        self.result_card.setVisible(False)
        self.error_card.setVisible(False)
        self.progress.setVisible(False)
        self.url_edit.setFocus()

    def _on_retry(self):
        self.error_card.setVisible(False)
        self.url_edit.setFocus()

    def _open_result_folder(self):
        if not self._last_result_path:
            return
        folder = os.path.dirname(self._last_result_path)
        if folder and os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _open_result_file(self):
        if self._last_result_path and os.path.exists(self._last_result_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_result_path))

    # ---------- Drag & drop ----------
    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasText() or md.hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        text = ""
        if md.hasText():
            text = md.text()
        elif md.hasUrls():
            urls = md.urls()
            if urls:
                text = urls[0].toString()
        url = find_url_in_text(text) or text
        if url:
            self.url_edit.setText(url.strip())


# ============================================================
# VISTA AVANZADA (la GUI clásica)
# ============================================================


class AdvancedView(QWidget):
    """Vista con todos los controles: presets, recortes, carpeta, log."""

    request_open_simple = Signal()
    request_open_folders = Signal()
    request_toggle_theme = Signal()
    request_start = Signal(str, str, str, str, str)  # url, preset, folder, start, end
    request_cancel = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._is_busy = False
        self._default_dirs = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        # Top bar
        top = QHBoxLayout()
        title = QLabel("VibeLoader · Modo avanzado")
        title.setObjectName("TitleLabel")
        top.addWidget(title)
        top.addStretch()
        self.theme_btn = QToolButton()
        self.theme_btn.setText("Tema")
        self.theme_btn.clicked.connect(self.request_toggle_theme)
        top.addWidget(self.theme_btn)
        self.simple_btn = QToolButton()
        self.simple_btn.setText("Modo simple")
        self.simple_btn.clicked.connect(self.request_open_simple)
        top.addWidget(self.simple_btn)
        layout.addLayout(top)

        sub = QLabel(
            "Descarga con yt-dlp, convierte con ffmpeg, y MP3 con metadatos. Acepta recortes."
        )
        sub.setObjectName("SubtitleLabel")
        layout.addWidget(sub)

        # URL
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("URL:"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Pega aquí la URL de YouTube / etc.")
        url_layout.addWidget(self.url_edit, 1)
        layout.addLayout(url_layout)

        # Recortes
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("Recortar (opcional):"))
        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText("Inicio (ej. 0:45)")
        self.start_edit.setFixedWidth(130)
        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText("Fin (ej. 1:30)")
        self.end_edit.setFixedWidth(130)
        time_layout.addWidget(self.start_edit)
        time_layout.addWidget(QLabel(" a "))
        time_layout.addWidget(self.end_edit)
        time_layout.addStretch()
        layout.addLayout(time_layout)

        # Carpeta de salida
        out_layout = QHBoxLayout()
        out_layout.addWidget(QLabel("Carpeta de salida:"))
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Elige dónde guardar el archivo…")
        browse_btn = QPushButton("Examinar")
        browse_btn.setObjectName("secondary")
        browse_btn.clicked.connect(self._elegir_carpeta)
        defaults_btn = QPushButton("Carpetas…")
        defaults_btn.setObjectName("secondary")
        defaults_btn.setToolTip("Cambiar las carpetas predeterminadas de cada modo")
        defaults_btn.clicked.connect(self.request_open_folders)
        out_layout.addWidget(self.out_edit, 1)
        out_layout.addWidget(browse_btn)
        out_layout.addWidget(defaults_btn)
        layout.addLayout(out_layout)

        # Preset
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Modo:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(ADVANCED_PRESETS))
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.preset_combo, 1)
        layout.addLayout(preset_layout)

        # Acción
        action = QHBoxLayout()
        self.start_btn = QPushButton("Descargar")
        self.start_btn.clicked.connect(self._on_start)
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setObjectName("secondary")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.request_cancel)
        action.addWidget(self.start_btn)
        action.addWidget(self.cancel_btn)
        layout.addLayout(action)

        # Progreso
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Esperando…")
        layout.addWidget(self.progress)

        # Log
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Aquí aparecerán los detalles del proceso…")
        layout.addWidget(self.log_box, 1)

    # ---------- Public API ----------
    def set_default_dirs(self, dirs: dict):
        self._default_dirs = dict(dirs)
        if not self.out_edit.text().strip():
            d = self._default_dirs.get(self.preset_combo.currentText())
            if d:
                self.out_edit.setText(d)

    def set_busy(self, busy: bool):
        self._is_busy = busy
        self.start_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.url_edit.setEnabled(not busy)
        self.start_edit.setEnabled(not busy)
        self.end_edit.setEnabled(not busy)
        self.out_edit.setEnabled(not busy)
        self.preset_combo.setEnabled(not busy)
        if busy:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat("Iniciando…")

    def set_progress(self, pct: int, detail: str):
        self.progress.setRange(0, 100)
        self.progress.setValue(pct)
        self.progress.setFormat(detail or f"{pct}%")

    def append_log(self, text: str):
        self.log_box.append(text)

    def show_success(self, file_path: str):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("Listo")

    def show_error(self, msg: str):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Error")
        self.append_log("⚠ " + friendly(msg))

    def show_cancelled(self):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Cancelado")

    # ---------- Internal ----------
    def _on_preset_changed(self, modo: str):
        d = self._default_dirs.get(modo)
        if not d:
            return
        if not self.out_edit.text().strip():
            self.out_edit.setText(d)

    def _elegir_carpeta(self):
        carpeta = QFileDialog.getExistingDirectory(
            self, "Elegir carpeta de salida", self.out_edit.text() or os.path.expanduser("~")
        )
        if carpeta:
            self.out_edit.setText(carpeta)

    def _on_start(self):
        url = self.url_edit.text().strip()
        carpeta = self.out_edit.text().strip()
        preset = self.preset_combo.currentText()
        start_t = self.start_edit.text().strip()
        end_t = self.end_edit.text().strip()
        if not url:
            self.append_log("⚠️ Pega o escribe una URL.")
            return
        if not carpeta:
            self.append_log("⚠️ Elige una carpeta de salida.")
            return
        self.request_start.emit(url, preset, carpeta, start_t, end_t)

    # ---------- Drag & drop ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasText() or e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        text = ""
        if e.mimeData().hasText():
            text = e.mimeData().text()
        elif e.mimeData().hasUrls():
            urls = e.mimeData().urls()
            if urls:
                text = urls[0].toString()
        url = find_url_in_text(text) or text
        if url:
            self.url_edit.setText(url.strip())


# ============================================================
# MAIN WINDOW
# ============================================================


class MainWindow(QMainWindow):
    request_metadata = Signal(str, int)

    def __init__(self):
        super().__init__()
        ensure_log_path()
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.setWindowTitle("VibeLoader ✨")
        self.setMinimumSize(820, 620)
        self.setWindowIcon(QIcon(resource_path("icono.ico")))

        loaded = load_default_dirs_from_settings(self.settings)
        self._pending_first_run = loaded is None
        self.default_dirs = loaded if loaded is not None else suggested_default_dirs()
        self.theme = str(self.settings.value("theme", "dark"))
        if self.theme not in THEMES:
            self.theme = "dark"
        self.recent_urls = load_recent_urls(self.settings)

        # Worker / metadata
        self.worker = None
        self.thread = None
        self._job_running = False
        self._job_cancelled = False
        self._job_failed = False
        self._active_view_for_job = None
        self._last_completed_path = None

        self._meta_thread = QThread(self)
        self._meta = MetadataFetcher()
        self._meta.moveToThread(self._meta_thread)
        self.request_metadata.connect(self._meta.fetch)
        self._meta_thread.start()

        # Tray for notifications
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self)
            icon_path = resource_path("icono.ico")
            if os.path.exists(icon_path):
                self.tray.setIcon(QIcon(icon_path))
            else:
                self.tray.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))
            self.tray.setToolTip("VibeLoader")

        # Views
        self.simple_view = SimpleView(self)
        self.advanced_view = AdvancedView(self)
        self.advanced_view.set_default_dirs(self.default_dirs)
        self.simple_view.update_folder_hint(self.default_dirs)
        self.simple_view.set_recents(self.recent_urls)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.simple_view)
        self.stack.addWidget(self.advanced_view)
        self.setCentralWidget(self.stack)

        # Wire signals
        self.simple_view.request_open_advanced.connect(self._show_advanced)
        self.simple_view.request_open_folders.connect(self._open_folders_dialog)
        self.simple_view.request_toggle_theme.connect(self._toggle_theme)
        self.simple_view.request_start.connect(self._start_from_simple)
        self.simple_view.request_cancel.connect(self._cancel_job)
        self.simple_view.request_fetch_metadata.connect(self._forward_metadata_request)

        self.advanced_view.request_open_simple.connect(self._show_simple)
        self.advanced_view.request_open_folders.connect(self._open_folders_dialog)
        self.advanced_view.request_toggle_theme.connect(self._toggle_theme)
        self.advanced_view.request_start.connect(self._start_from_advanced)
        self.advanced_view.request_cancel.connect(self._cancel_job)

        self._meta.fetched.connect(self.simple_view.on_metadata)
        self._meta.failed.connect(self.simple_view.on_metadata_failed)

        # Theme & arranque
        self._apply_theme()

        # Start log
        self._log_to_advanced("🔎 Verificando herramientas…")
        for t in ("ffmpeg", "ffprobe"):
            ok = check_tool(t)
            self._log_to_advanced(
                f"{'✅' if ok else '❌'} {t}: {'OK' if ok else 'NO encontrado en PATH'}"
            )
        if not check_tool("ffmpeg") or not check_tool("ffprobe"):
            self._log_to_advanced(
                "⚠️ Necesitas ffmpeg y ffprobe en el PATH. Sin ellos no funcionan los modos WhatsApp, Auto ni MP3 con portada."
            )

        # Auto-update opcional
        if self.settings.value("auto_update_ytdlp", False, type=bool):
            self._log_to_advanced("🔄 Buscando actualización de yt-dlp…")
            maybe_update_ytdlp_in_background(self._log_to_advanced)

        # Decide vista inicial
        last_view = str(self.settings.value("last_view", "simple"))
        if self._pending_first_run or last_view != "advanced":
            self._show_simple()
        else:
            self._show_advanced()

        if self._pending_first_run:
            QTimer.singleShot(0, self._first_run_setup)
        else:
            QApplication.instance().applicationStateChanged.connect(
                self._on_app_state_changed
            )

        QTimer.singleShot(300, self.simple_view.maybe_autopaste_clipboard)

    # ---------- Tema ----------
    def _apply_theme(self):
        QApplication.instance().setStyleSheet(build_stylesheet(self.theme))

    def _toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self.settings.setValue("theme", self.theme)
        self._apply_theme()

    # ---------- Navegación ----------
    def _show_simple(self):
        self.stack.setCurrentWidget(self.simple_view)
        self.settings.setValue("last_view", "simple")

    def _show_advanced(self):
        self.stack.setCurrentWidget(self.advanced_view)
        self.settings.setValue("last_view", "advanced")

    # ---------- App focus ----------
    def _on_app_state_changed(self, state):
        if state == Qt.ApplicationState.ApplicationActive:
            QTimer.singleShot(150, self.simple_view.maybe_autopaste_clipboard)

    # ---------- Carpetas ----------
    def _first_run_setup(self):
        dlg = DefaultFoldersConfigDialog(self, dict(self.default_dirs), first_run=True)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.default_dirs = dlg.get_paths()
        save_default_dirs_to_settings(self.settings, self.default_dirs)
        self._refresh_dirs_in_views()
        QApplication.instance().applicationStateChanged.connect(
            self._on_app_state_changed
        )

    def _open_folders_dialog(self):
        dlg = DefaultFoldersConfigDialog(self, dict(self.default_dirs), first_run=False)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.default_dirs = dlg.get_paths()
        save_default_dirs_to_settings(self.settings, self.default_dirs)
        self._refresh_dirs_in_views()

    def _refresh_dirs_in_views(self):
        self.simple_view.update_folder_hint(self.default_dirs)
        self.advanced_view.set_default_dirs(self.default_dirs)

    # ---------- Metadatos ----------
    def _forward_metadata_request(self, url: str, token: int):
        self.request_metadata.emit(url, token)

    # ---------- Job ----------
    def _start_from_simple(self, url: str, preset: str):
        folder = self.default_dirs.get(preset, "")
        if not folder:
            folder = suggested_default_dirs().get(preset, os.path.expanduser("~"))
        self._launch_job(url, preset, folder, "", "", source_view=self.simple_view)

    def _start_from_advanced(
        self, url: str, preset: str, folder: str, start_t: str, end_t: str
    ):
        self._launch_job(url, preset, folder, start_t, end_t, source_view=self.advanced_view)

    def _launch_job(self, url, preset, folder, start_t, end_t, source_view):
        if self._job_running:
            self._log_to_advanced("⚠️ Ya hay una descarga en curso.")
            return
        self._job_running = True
        self._job_cancelled = False
        self._job_failed = False
        self._active_view_for_job = source_view
        self._remember_url(url)

        source_view.set_busy(True)
        if source_view is self.simple_view:
            self.advanced_view.set_busy(True)
        else:
            self.simple_view.set_busy(True)

        self.thread = QThread()
        self.worker = Worker(url, folder, preset, start_t, end_t)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self._on_worker_log)
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.completed.connect(self._on_worker_completed)
        self.worker.error.connect(self._on_worker_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _cancel_job(self):
        if self.worker is not None and self._job_running:
            self._job_cancelled = True
            self.worker.request_cancel()
            self._log_to_advanced("⏹️ Cancelación solicitada…")

    def _on_worker_log(self, msg: str):
        self.advanced_view.append_log(msg)
        append_log_file(msg)

    def _on_worker_progress(self, pct: int, msg: str):
        self.advanced_view.set_progress(pct, msg)
        self.simple_view.set_progress(pct, msg)

    def _on_worker_completed(self, file_path: str):
        self._last_completed_path = file_path

    def _on_worker_error(self, msg: str):
        self._job_failed = True
        self.advanced_view.show_error(msg)
        self.simple_view.show_error(msg)
        if self.tray and not self.isActiveWindow():
            self.tray.show()
            self.tray.showMessage(
                "VibeLoader", "Hubo un problema con la descarga.", QSystemTrayIcon.MessageIcon.Warning, 5000
            )

    def _on_worker_finished(self):
        path = getattr(self, "_last_completed_path", None)
        self._job_running = False
        self.advanced_view.set_busy(False)
        self.simple_view.set_busy(False)
        if self._job_cancelled:
            self.advanced_view.show_cancelled()
            self.simple_view.show_cancelled()
        elif self._job_failed:
            pass
        else:
            self.advanced_view.show_success(path or "")
            self.simple_view.show_success(path or "")
            if self.tray and not self.isActiveWindow():
                self.tray.show()
                self.tray.showMessage(
                    "VibeLoader",
                    "Descarga lista.",
                    QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )
        self._last_completed_path = None

    # ---------- Recientes ----------
    def _remember_url(self, url: str):
        if not url:
            return
        urls = [u for u in self.recent_urls if u != url]
        urls.insert(0, url)
        self.recent_urls = urls[:5]
        save_recent_urls(self.settings, self.recent_urls)
        self.simple_view.set_recents(self.recent_urls)

    # ---------- Logging ----------
    def _log_to_advanced(self, msg: str):
        self.advanced_view.append_log(msg)
        append_log_file(msg)

    # ---------- Cierre ----------
    def closeEvent(self, e):
        try:
            if self.worker is not None and self._job_running:
                self.worker.request_cancel()
            self._meta_thread.quit()
            self._meta_thread.wait(1500)
        except Exception:
            pass
        super().closeEvent(e)


# ============================================================
# MAIN
# ============================================================


def main():
    ensure_log_path()
    app = QApplication(sys.argv)
    app.setApplicationName(SETTINGS_APP)
    app.setOrganizationName(SETTINGS_ORG)

    splash = None
    splash_path = resource_path("splash_screen.png")
    if os.path.isfile(splash_path):
        pix = QPixmap(splash_path)
        if not pix.isNull():
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                max_w = max(120, int(geo.width() * 0.25))
                max_h = max(120, int(geo.height() * 0.25))
                pix = pix.scaled(
                    max_w,
                    max_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            splash = QSplashScreen(pix, Qt.WindowType.WindowStaysOnTopHint)
            if screen is not None:
                fg = splash.frameGeometry()
                fg.moveCenter(geo.center())
                splash.move(fg.topLeft())
            splash.show()
            app.processEvents()

    window = MainWindow()
    window.show()
    if splash is not None:
        splash.finish(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
