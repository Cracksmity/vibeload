"""Helpers puros: tiempos, nombres de archivo, herramientas externas."""
import os
import re
import shutil

_INTERMEDIATE_RE = re.compile(
    r"(\.vlsrc\.|\.vlsub\.|\.temp\.|\.part$|\.part-frag|\.ytdl$|\.f[\w-]+\.(mp4|webm|m4a|mkv|mp3|opus|ogg|aac|flac|wav)$)",
    re.IGNORECASE,
)
_THUMB_EXTS = (".webp", ".jpg", ".jpeg", ".png")


class FolderSnapshot:
    """Recuerda qué había en una carpeta para borrar SOLO lo que creó el trabajo.

    Nunca se borra un archivo que ya existía antes de empezar (p. ej. un .flac
    del usuario con el mismo nombre que la canción descargada).
    """

    def __init__(self, folder: str):
        self.folder = folder
        self.before = self._names()

    def _names(self) -> set:
        try:
            return set(os.listdir(self.folder))
        except OSError:
            return set()

    def new_files(self) -> list:
        out = []
        for name in sorted(self._names() - self.before):
            p = os.path.join(self.folder, name)
            if os.path.isfile(p):
                out.append(p)
        return out

    def leftovers_after_success(self, result_path: str | None) -> list:
        """Intermedios y portadas sueltas creados por el trabajo (no el resultado)."""
        res = os.path.normcase(os.path.abspath(result_path)) if result_path else None
        res_base = os.path.splitext(res)[0] if res else None
        out = []
        for p in self.new_files():
            ap = os.path.normcase(os.path.abspath(p))
            if ap == res:
                continue
            base, ext = os.path.splitext(ap)
            if _INTERMEDIATE_RE.search(os.path.basename(p)) or (
                res_base and base == res_base and ext.lower() in _THUMB_EXTS
            ):
                out.append(p)
        return out

    def leftovers_after_failure(self, partial_outputs=()) -> list:
        """Intermedios creados por el trabajo + salidas a medias que antes no existían."""
        partial = {os.path.normcase(os.path.abspath(p)) for p in partial_outputs if p}
        out = []
        for p in self.new_files():
            ap = os.path.normcase(os.path.abspath(p))
            if ap in partial or _INTERMEDIATE_RE.search(os.path.basename(p)):
                out.append(p)
        return out


def remove_files(paths, logger):
    for p in paths:
        try:
            if os.path.exists(p):
                os.remove(p)
                logger(f"🧹 Borrado archivo temporal: {os.path.basename(p)}")
        except OSError as e:
            logger(f"⚠️ No se pudo borrar {p}: {e}")


def check_tool(tool_name):
    return shutil.which(tool_name) is not None


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
