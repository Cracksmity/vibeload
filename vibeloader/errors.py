"""Excepciones propias y traducción de errores a mensajes amigables."""

# Qué puede hacer el usuario ante cada error (la interfaz muestra un botón).
ACTION_RETRY = "retry"  # Reintentar
ACTION_COOKIES = "cookies"  # Usar la sesión del navegador y reintentar
ACTION_UPDATE = "update"  # Actualizar el motor de descargas (yt-dlp)
ACTION_WAIT = "wait"  # Reintentar solo en unos minutos
ACTION_FFMPEG = "ffmpeg"  # Instalar ffmpeg
ACTION_FOLDER = "folder"  # Elegir otra carpeta

# (texto a buscar, mensaje para el usuario, acción). Se recorre en orden: lo
# más específico va primero. Los mensajes no mencionan herramientas internas
# ni mandan a otro modo: el botón de la acción resuelve el problema.
FRIENDLY_ERRORS = (
    ("Sign in to confirm your age", "Este video pide iniciar sesión (tiene restricción de edad).", ACTION_COOKIES),
    ("Sign in to confirm", "YouTube pide confirmar que no eres un robot.", ACTION_COOKIES),
    ("Private video", "Este video es privado y no se puede descargar.", None),
    ("Video unavailable", "Este video ya no está disponible (lo borraron o está bloqueado en tu país).", None),
    ("video is unavailable", "Este video ya no está disponible (lo borraron o está bloqueado en tu país).", None),
    ("HTTP Error 403", "El sitio rechazó la descarga. Suele arreglarse actualizando el motor de descargas.", ACTION_UPDATE),
    ("HTTP Error 404", "No encontramos nada en ese enlace. Revisa que esté completo.", None),
    ("HTTP Error 429", "El sitio pidió una pausa por muchas descargas seguidas.", ACTION_WAIT),
    ("Requested format is not available", "Este video no está disponible en ese formato. Prueba con otro.", ACTION_UPDATE),
    ("Unable to extract", "Este sitio cambió y no pudimos leer el video. Suele arreglarse actualizando el motor de descargas.", ACTION_UPDATE),
    ("Cannot parse data", "Facebook devolvió una página que no pudimos leer. Actualiza el motor de descargas o prueba en unos minutos.", ACTION_UPDATE),
    ("Impersonate target", "Falta un componente para Facebook e Instagram (curl_cffi). Reinstala VibeLoader.", None),
    ("Unsupported URL", "Ese sitio todavía no es compatible.", None),
    ("Unknown encoder 'libx265'", "El ffmpeg instalado no trae H.265, que usa el formato Cursos. Instala el de VibeLoader.", ACTION_FFMPEG),
    ("ffmpeg not found", "Falta ffmpeg, el componente que une y convierte los videos.", ACTION_FFMPEG),
    ("ffprobe not found", "Falta ffmpeg, el componente que une y convierte los videos.", ACTION_FFMPEG),
    ("WinError 5", "No hay permiso para guardar en esa carpeta. Elige otra.", ACTION_FOLDER),
    ("WinError 32", "El archivo está abierto en otro programa. Ciérralo y vuelve a intentar.", ACTION_RETRY),
    ("No space left", "El disco está lleno. Libera espacio y vuelve a intentar.", ACTION_RETRY),
    ("Cancelado", "Cancelaste la descarga.", None),
)


def explain(msg: str) -> tuple[str, str | None]:
    """(mensaje para el usuario, acción sugerida o None)."""
    if not msg:
        return "Algo salió mal.", ACTION_RETRY
    low = msg.lower()
    for needle, friendly_msg, action in FRIENDLY_ERRORS:
        if needle.lower() in low:
            return friendly_msg, action
    first = msg.strip().split("\n")[0]
    if first.startswith("ERROR: "):
        first = first[len("ERROR: "):]
    return first[:300], ACTION_RETRY


def friendly(msg: str) -> str:
    return explain(msg)[0]


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
