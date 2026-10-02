"""Excepciones propias y traducción de errores a mensajes amigables."""

# (texto a buscar, mensaje para el usuario). Se recorre en orden: lo más
# específico va primero.
FRIENDLY_ERRORS = (
    (
        "Sign in to confirm your age",
        "Este video tiene restricción de edad. Activa «Usar cookies del navegador» "
        "en el modo avanzado (con una sesión de YouTube iniciada en ese navegador).",
    ),
    (
        "Sign in to confirm",
        "YouTube pide confirmar que no eres un bot. Espera unos minutos o activa "
        "«Usar cookies del navegador» en el modo avanzado.",
    ),
    ("Private video", "Este video es privado, no se puede descargar."),
    (
        "Video unavailable",
        "Este video no está disponible (puede haber sido eliminado o restringido por país).",
    ),
    (
        "HTTP Error 403",
        "El servidor rechazó la descarga (403). Probablemente yt-dlp necesita actualizarse "
        "(botón «Actualizar yt-dlp» en el modo avanzado).",
    ),
    ("HTTP Error 404", "Enlace no encontrado (404). Revisa que la URL esté correcta."),
    ("HTTP Error 429", "Muchas peticiones seguidas (429). Espera un par de minutos y vuelve a intentar."),
    (
        "Requested format is not available",
        "El sitio no ofrece un formato compatible para este video. Prueba otro modo "
        "o actualiza yt-dlp.",
    ),
    (
        "Unable to extract",
        "yt-dlp no pudo leer este enlace. Probablemente necesita actualizarse "
        "(botón «Actualizar yt-dlp» en el modo avanzado).",
    ),
    (
        "Cannot parse data",
        "Facebook/Meta devolvió una página que yt-dlp no pudo leer. Actualiza yt-dlp "
        "y vuelve a intentarlo en unos minutos.",
    ),
    (
        "Impersonate target",
        "Falta el componente de huella de navegador (curl_cffi) que usan Facebook/Instagram. "
        "Reinstala las dependencias con requirements.txt.",
    ),
    ("Unsupported URL", "Ese enlace no está soportado. Prueba con otro de YouTube u otro sitio."),
    (
        "Unknown encoder 'libx265'",
        "Tu ffmpeg no incluye H.265 (libx265), que necesita el Modo Cursos. "
        "Usa el ffmpeg que descarga VibeLoader o una build «full».",
    ),
    ("ffmpeg not found", "No se encontró ffmpeg. VibeLoader puede descargarlo por ti."),
    ("ffprobe not found", "No se encontró ffprobe. VibeLoader puede descargarlo por ti."),
    ("WinError 5", "Permiso denegado al guardar. Elige otra carpeta o cierra el archivo si lo tienes abierto."),
    ("WinError 32", "El archivo está abierto en otro programa. Ciérralo y vuelve a intentar."),
    ("No space left", "No hay espacio libre en el disco. Libera espacio y vuelve a intentar."),
    ("Cancelado", "Cancelaste la descarga."),
)


def friendly(msg: str) -> str:
    if not msg:
        return "Algo salió mal."
    low = msg.lower()
    for needle, friendly_msg in FRIENDLY_ERRORS:
        if needle.lower() in low:
            return friendly_msg
    first = msg.strip().split("\n")[0]
    if first.startswith("ERROR: "):
        first = first[len("ERROR: "):]
    return first[:300]


class UserCancelledError(Exception):
    """El usuario canceló la descarga o la conversión."""


class ClipTimestampError(Exception):
    """Marcas de tiempo de recorte fuera del rango del video."""


class FfmpegError(Exception):
    """ffmpeg terminó con error; el mensaje lleva la causa real (última línea de stderr)."""


class TargetSizeTooSmallError(Exception):
    """El tamaño objetivo es demasiado chico para la duración del video."""


class PlaylistNotSupportedError(Exception):
    """El enlace es una lista de reproducción y el modo elegido baja un solo video."""

    def __init__(self, title: str = ""):
        self.title = title
        nombre = f" «{title}»" if title else ""
        super().__init__(
            f"Este enlace es una lista de reproducción{nombre}. "
            "Abre un video de la lista y copia su enlace."
        )
