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


URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# Sitios conocidos: solo se usan para pegar automáticamente desde el
# portapapeles (no molestar con cualquier enlace copiado). Para descargar se
# acepta cualquier http(s): yt-dlp soporta más de 1.800 sitios.
SUPPORTED_HOSTS = (
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "fb.watch",
    "threads.net",
    "twitch.tv",
    "soundcloud.com",
    "vimeo.com",
    "dailymotion.com",
    "reddit.com",
    "bilibili.com",
    "kick.com",
)

_TRAILING_PUNCT = ".,;:!?\"'»›>]}"


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def find_url_in_text(text: str):
    """Primer enlace http(s) del texto, sin la puntuación que suele pegarse al final."""
    if not text:
        return None
    m = URL_RE.search(text)
    if not m:
        return None
    url = m.group(0)
    while url:
        if url[-1] in _TRAILING_PUNCT:
            url = url[:-1]
        elif url[-1] == ")" and url.count("(") < url.count(")"):
            url = url[:-1]
        else:
            break
    return url or None


def is_http_url(url: str) -> bool:
    """URL http(s) con un hostname real (con punto). Sirve para habilitar la descarga."""
    if not url:
        return False
    try:
        p = urlparse(url.strip())
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    return p.scheme in ("http", "https") and "." in host and " " not in url.strip()


def looks_like_supported_url(url: str) -> bool:
    """¿Es de un sitio conocido? Compara por hostname (antes 'netflix.com' pasaba por 'x.com')."""
    if not is_http_url(url):
        return False
    host = _url_hostname_lower(url.strip())
    return any(_host_matches(host, d) for d in SUPPORTED_HOSTS)
