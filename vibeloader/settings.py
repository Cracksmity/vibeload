"""Persistencia en QSettings: carpetas por modo y enlaces recientes."""
import os

from PySide6.QtCore import QSettings

from .config import (
    PRESET_CAR,
    PRESET_CURSOS,
    PRESET_DIRECTO,
    PRESET_TAMANO,
    PRESET_MAX,
    PRESET_MP3,
    PRESET_WHATSAPP,
    SETTINGS_KEYS,
)

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
        PRESET_DIRECTO: os.path.join(base, "VibeLoader", "Directo"),
        PRESET_CURSOS: os.path.join(base, "VibeLoader", "Cursos"),
        PRESET_TAMANO: os.path.join(base, "VibeLoader", "Comprimidos"),
    }


def load_default_dirs_from_settings(settings: QSettings):
    if not settings.value("defaults_configured", False, type=bool):
        return None
    out = {}
    for preset, key in SETTINGS_KEYS.items():
        out[preset] = str(settings.value(key) or "").strip()
    if not all(out.get(p) for p in (PRESET_WHATSAPP, PRESET_MAX, PRESET_MP3)):
        return None
    # Modos agregados después de la primera configuración: usar la carpeta sugerida.
    suggested = suggested_default_dirs()
    for preset in SETTINGS_KEYS:
        if not out.get(preset):
            out[preset] = suggested[preset]
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
