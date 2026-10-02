"""Detección de hosts y validación de URLs."""
import re
from urllib.parse import urlparse

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
