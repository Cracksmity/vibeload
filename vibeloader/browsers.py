"""Qué navegador usar para tomar la sesión (cookies) cuando un sitio la pide."""
import os

NAMES = {"firefox": "Firefox", "chrome": "Chrome", "edge": "Edge", "brave": "Brave", "opera": "Opera"}


def browser_display_name(browser: str | None) -> str:
    return NAMES.get(browser or "", browser or "")


def detect_cookie_browser() -> str:
    """Firefox si está instalado (no bloquea sus cookies abierto); si no, Chrome o Edge."""
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    if appdata and os.path.isdir(os.path.join(appdata, "Mozilla", "Firefox", "Profiles")):
        return "firefox"
    if local and os.path.isdir(os.path.join(local, "Google", "Chrome", "User Data")):
        return "chrome"
    return "edge"
