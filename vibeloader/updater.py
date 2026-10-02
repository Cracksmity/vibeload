"""Actualización de yt-dlp sin recompilar el .exe.

YouTube cambia seguido y un yt-dlp congelado dentro del .exe deja de funcionar
en semanas. Solución: se descarga la wheel oficial de PyPI (verificando su
SHA-256) a %LOCALAPPDATA%/VibeLoader/ytdlp_lib y, al arrancar, esa carpeta va
primero en sys.path, así gana sobre la copia embebida.

- yt-dlp y yt-dlp-ejs son Python puro: una wheel es un zip que se extrae tal cual.
- activate_overlay() debe llamarse antes de cualquier `import yt_dlp`.
- En modo desarrollo (sin congelar) no se usa: ahí se actualiza con pip.
"""
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.request
import zipfile

from .config import BROWSER_UA, is_frozen
from .tools import app_data_dir

PYPI_URL = "https://pypi.org/pypi/{name}/json"
PYPI_VERSION_URL = "https://pypi.org/pypi/{name}/{version}/json"


def overlay_dir() -> str:
    return os.path.join(app_data_dir(), "ytdlp_lib")


def _marker_path(base: str) -> str:
    return os.path.join(base, "VIBELOADER_OVERLAY.json")


def parse_version(v: str) -> tuple:
    """'2026.08.19' / '2026.8.19.1' → (2026, 8, 19, 1). Comparación numérica."""
    return tuple(int(x) for x in re.findall(r"\d+", v or "")) or (0,)


def embedded_ytdlp_version() -> str:
    """Versión de yt-dlp que viene dentro del .exe (la escribe el script de build)."""
    try:
        from ._build_info import YTDLP_VERSION

        return YTDLP_VERSION
    except Exception:
        return "0"


def read_overlay_info(base: str | None = None) -> dict:
    try:
        with open(_marker_path(base or overlay_dir()), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def activate_overlay() -> str | None:
    """Pone la copia actualizada de yt-dlp primero en sys.path si es más nueva
    que la embebida. Devuelve la versión activada o None."""
    if not is_frozen():
        return None
    base = overlay_dir()
    info = read_overlay_info(base)
    ver = info.get("yt_dlp")
    if not ver or not os.path.isdir(os.path.join(base, "yt_dlp")):
        return None
    if parse_version(ver) <= parse_version(embedded_ytdlp_version()):
        return None  # el .exe nuevo ya trae una versión igual o más reciente
    if base not in sys.path:
        sys.path.insert(0, base)
    return ver


# ------------------------------------------------------------
# Descarga desde PyPI
# ------------------------------------------------------------


def _get_json(url: str, timeout: float = 20) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _pick_wheel(release_files: list) -> dict:
    for f in release_files:
        if f.get("packagetype") == "bdist_wheel" and f.get("filename", "").endswith("py3-none-any.whl"):
            return f
    raise RuntimeError("No hay wheel universal en PyPI.")


def _download_verified(file_info: dict, timeout: float = 60) -> bytes:
    req = urllib.request.Request(file_info["url"], headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    expected = (file_info.get("digests") or {}).get("sha256")
    if not expected or hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError("La descarga de PyPI no coincide con su SHA-256; se descarta.")
    return data


def _ejs_requirement(info: dict) -> str | None:
    """Versión exacta de yt-dlp-ejs que pide esa versión de yt-dlp (extra 'default')."""
    for req in info.get("requires_dist") or []:
        m = re.match(r"yt-dlp-ejs\s*==\s*([\w.]+)", req)
        if m:
            return m.group(1)
    return None


def _extract_wheel(data: bytes, dest: str):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            # Solo el código; .dist-info y .data (manuales, completions) no hacen falta.
            if ".dist-info/" in member or ".data/" in member or member.startswith(("..", "/")):
                continue
            z.extract(member, dest)


def latest_ytdlp_version() -> str:
    return _get_json(PYPI_URL.format(name="yt-dlp"))["info"]["version"]


def install_latest_ytdlp(current_version: str, logger=print) -> str | None:
    """Descarga e instala la última versión si es más nueva que current_version.

    Devuelve la versión instalada, o None si ya estaba al día. Se aplica al
    reiniciar la app (los módulos ya importados no se pueden reemplazar en caliente).
    """
    data = _get_json(PYPI_URL.format(name="yt-dlp"))
    latest = data["info"]["version"]
    if parse_version(latest) <= parse_version(current_version):
        logger(f"✅ yt-dlp está al día ({current_version}).")
        return None

    logger(f"⬇️ Descargando yt-dlp {latest} desde PyPI…")
    wheel = _download_verified(_pick_wheel(data["urls"]))

    ejs_ver = _ejs_requirement(data["info"])
    ejs_wheel = None
    if ejs_ver:
        ejs_data = _get_json(PYPI_VERSION_URL.format(name="yt-dlp-ejs", version=ejs_ver))
        ejs_wheel = _download_verified(_pick_wheel(ejs_data["urls"]))

    base = overlay_dir()
    tmp = base + ".new"
    old = base + ".old"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    _extract_wheel(wheel, tmp)
    if ejs_wheel:
        _extract_wheel(ejs_wheel, tmp)
    with open(_marker_path(tmp), "w", encoding="utf-8") as f:
        json.dump({"yt_dlp": latest, "yt_dlp_ejs": ejs_ver, "installed": time.time()}, f)

    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(base):
        os.replace(base, old)
    os.replace(tmp, base)
    shutil.rmtree(old, ignore_errors=True)  # si algo sigue abierto, se limpia la próxima vez
    logger(f"✅ yt-dlp {latest} instalado. Reinicia VibeLoader para usarlo.")
    return latest


def pip_update_ytdlp(logger=print) -> bool:
    """Modo desarrollo: actualiza con pip en el entorno actual."""
    import subprocess

    from .tools import no_window_flags

    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "yt-dlp[default,curl-cffi]"],
        capture_output=True,
        text=True,
        timeout=300,
        creationflags=no_window_flags(),
    )
    if r.returncode != 0:
        raise RuntimeError("pip no pudo actualizar yt-dlp: " + (r.stderr or "").strip()[-300:])
    logger("✅ yt-dlp actualizado con pip (se usa al reiniciar la app).")
    return True


def should_check_now(last_check: float, interval_hours: float = 24) -> bool:
    return (time.time() - (last_check or 0)) >= interval_hours * 3600


# ------------------------------------------------------------
# ffmpeg bajo demanda (builds de BtbN en GitHub)
# ------------------------------------------------------------

FFMPEG_RELEASE_API = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
_FFMPEG_ZIP_RE = re.compile(r"ffmpeg-n(\d+)\.(\d+)-latest-win64-gpl-\d+\.\d+\.zip$")


def pick_ffmpeg_asset(assets: list) -> dict:
    """La versión estable más nueva (gpl: trae libx264, libx265, NVENC, QSV y AMF)."""
    best, best_v = None, (-1, -1)
    for a in assets:
        m = _FFMPEG_ZIP_RE.match(a.get("name", ""))
        if m:
            v = (int(m.group(1)), int(m.group(2)))
            if v > best_v:
                best, best_v = a, v
    if best is None:
        for a in assets:
            if a.get("name") == "ffmpeg-master-latest-win64-gpl.zip":
                return a
        raise RuntimeError("No se encontró un ffmpeg para Windows en la última versión de BtbN.")
    return best


def ffmpeg_release_info() -> tuple:
    """(asset del zip, sha256 esperado) de la última versión publicada."""
    rel = _get_json(FFMPEG_RELEASE_API)
    assets = rel.get("assets") or []
    asset = pick_ffmpeg_asset(assets)
    sums = next((a for a in assets if a.get("name") == "checksums.sha256"), None)
    expected = None
    if sums:
        req = urllib.request.Request(sums["browser_download_url"], headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            for line in r.read().decode("utf-8", "replace").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1].lstrip("*") == asset["name"]:
                    expected = parts[0].lower()
    if not expected:
        raise RuntimeError("No se pudo obtener la suma SHA-256 de ffmpeg; se cancela por seguridad.")
    return asset, expected


def install_ffmpeg(dest_bin: str, progress=None, is_cancelled=lambda: False, asset_info=None) -> str:
    """Descarga el zip, verifica SHA-256 y extrae ffmpeg.exe y ffprobe.exe en dest_bin."""
    asset, expected = asset_info or ffmpeg_release_info()
    total = int(asset.get("size") or 0)
    os.makedirs(os.path.dirname(dest_bin), exist_ok=True)
    tmp_zip = os.path.join(os.path.dirname(dest_bin), "ffmpeg_download.zip.part")
    h = hashlib.sha256()
    done = 0
    try:
        req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp_zip, "wb") as f:
            while True:
                if is_cancelled():
                    raise InterruptedError("Descarga de ffmpeg cancelada.")
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if h.hexdigest() != expected:
            raise RuntimeError("El archivo de ffmpeg descargado no coincide con su SHA-256; se descarta.")
        os.makedirs(dest_bin, exist_ok=True)
        wanted = {"ffmpeg.exe", "ffprobe.exe"}
        with zipfile.ZipFile(tmp_zip) as z:
            for member in z.namelist():
                name = member.rsplit("/", 1)[-1]
                if name in wanted and "/bin/" in member:
                    with z.open(member) as src, open(os.path.join(dest_bin, name + ".new"), "wb") as out:
                        shutil.copyfileobj(src, out)
                    wanted.discard(name)
        if wanted:
            raise RuntimeError("El zip de ffmpeg no trae " + ", ".join(sorted(wanted)))
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            os.replace(os.path.join(dest_bin, name + ".new"), os.path.join(dest_bin, name))
        return asset["name"]
    finally:
        try:
            os.remove(tmp_zip)
        except OSError:
            pass
