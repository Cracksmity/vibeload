"""Constantes de la app, presets y rutas de recursos."""
import os
import sys

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

# Raíz del proyecto (donde están icono.ico y splash_screen.png) cuando no está congelado.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


PRESET_WHATSAPP = "Modo WhatsApp (Base)"
PRESET_MAX = "Modo Video Max"
PRESET_MP3 = "Modo Audio MP3"
PRESET_CAR = "Modo Auto"
PRESET_DIRECTO = "Modo Descarga Directa"

ALL_PRESETS = (PRESET_WHATSAPP, PRESET_MAX, PRESET_MP3, PRESET_CAR, PRESET_DIRECTO)
ADVANCED_PRESETS = (PRESET_WHATSAPP, PRESET_MAX, PRESET_MP3, PRESET_CAR, PRESET_DIRECTO)

SETTINGS_KEYS = {
    PRESET_WHATSAPP: "dir_whatsapp",
    PRESET_MAX: "dir_max",
    PRESET_MP3: "dir_mp3",
    PRESET_CAR: "dir_car",
    PRESET_DIRECTO: "dir_directo",
}


def resource_path(relative_name: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_name)
    return os.path.join(PROJECT_ROOT, relative_name)


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)
