"""Descarga de miniaturas para la vista previa."""
import urllib.request
from urllib.parse import urlparse

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from .config import BROWSER_UA


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


def image_from_bytes(data: bytes, max_w: int = 160, max_h: int = 90) -> QImage | None:
    """Decodifica y escala con QImage: se puede usar fuera del hilo de la GUI
    (QPixmap no; usarlo en un hilo secundario puede cerrar la app)."""
    if not data:
        return None
    img = QImage()
    if not img.loadFromData(data) or img.isNull():
        return None
    return img.scaled(
        max_w,
        max_h,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


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
