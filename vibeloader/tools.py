"""Localiza herramientas externas (ffmpeg, ffprobe) y opciones de subprocess."""
import os
import shutil
import subprocess
import sys


def app_data_dir() -> str:
    """%LOCALAPPDATA%\\VibeLoader (o ~/VibeLoader fuera de Windows)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "VibeLoader")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return base
    return path


def local_ffmpeg_dir() -> str:
    """Carpeta donde VibeLoader instala su propio ffmpeg (descarga bajo demanda)."""
    return os.path.join(app_data_dir(), "ffmpeg", "bin")


def _find(name: str) -> str | None:
    exe = name + (".exe" if sys.platform == "win32" else "")
    local = os.path.join(local_ffmpeg_dir(), exe)
    if os.path.isfile(local):
        return local
    return shutil.which(name)


def ffmpeg_path() -> str | None:
    return _find("ffmpeg")


def ffprobe_path() -> str | None:
    return _find("ffprobe")


def ffmpeg_exe() -> str:
    """Ruta a ffmpeg o el nombre pelado (para que el error sea 'no encontrado')."""
    return ffmpeg_path() or "ffmpeg"


def ffprobe_exe() -> str:
    return ffprobe_path() or "ffprobe"


def ffmpeg_available() -> bool:
    return ffmpeg_path() is not None and ffprobe_path() is not None


def ffmpeg_location_for_ytdlp() -> str | None:
    """Carpeta que contiene ffmpeg y ffprobe, para la opción 'ffmpeg_location' de yt-dlp."""
    p = ffmpeg_path()
    return os.path.dirname(p) if p else None


def no_window_flags() -> int:
    """Evita que se abra una consola por cada subprocess en el .exe sin consola."""
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0
