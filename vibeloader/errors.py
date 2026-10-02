"""Excepciones propias y traducción de errores a mensajes amigables."""

FRIENDLY_ERRORS = (
    (
        "Sign in to confirm",
        "YouTube pide iniciar sesión para confirmar que no eres un bot. Espera unos minutos y vuelve a intentarlo.",
    ),
    ("Private video", "Este video es privado, no se puede descargar."),
    (
        "Video unavailable",
        "Este video no está disponible (puede haber sido eliminado o restringido por país).",
    ),
    (
        "HTTP Error 403",
        "El servidor rechazó la descarga (403). Probablemente yt-dlp necesita actualizarse.",
    ),
    (
        "HTTP Error 404",
        "Enlace no encontrado (404). Revisa que la URL esté correcta.",
    ),
    (
        "HTTP Error 429",
        "Muchas peticiones seguidas (429). Espera un par de minutos y vuelve a intentar.",
    ),
    (
        "Unable to extract",
        "yt-dlp no pudo leer este enlace. Probablemente necesita actualizarse.",
    ),
    (
        "Cannot parse data",
        "Facebook/Meta a veces devuelve una página que yt-dlp no puede leer. "
        "Actualiza yt-dlp (ideal nightly), instala el paquete curl-cffi, y para enlaces Meta "
        "esta app ya usa impersonación de navegador automáticamente.",
    ),
    (
        "Impersonate target",
        "La huella TLS del navegador no está disponible. "
        "En yt-dlp, `curl-cffi` suele necesitarse en la rama 0.14.x (no 0.15.x). "
        "Prueba: `pip install \"curl-cffi<0.15\"` y vuelve a intentarlo.",
    ),
    (
        "Unsupported URL",
        "Ese enlace no está soportado. Prueba con otro de YouTube u otro sitio.",
    ),
    (
        "ffmpeg not found",
        "No se encontró ffmpeg. Instálalo y agrégalo al PATH.",
    ),
    (
        "ffprobe not found",
        "No se encontró ffprobe. Instálalo y agrégalo al PATH.",
    ),
    (
        "no se encontró 'ffmpeg'",
        "No se encontró ffmpeg en el PATH del sistema.",
    ),
    (
        "no se encontró ffmpeg",
        "No se encontró ffmpeg. Instálalo y agrégalo al PATH.",
    ),
    (
        "ffmpeg exited with code",
        "Error al procesar o recortar el video con FFmpeg. El stream del video puede requerir actualización de yt-dlp.",
    ),
    (
        "WinError 5",
        "Permiso denegado al guardar. Elige otra carpeta o cierra el archivo si lo tienes abierto.",
    ),
    (
        "No space left",
        "No hay espacio libre en el disco. Libera espacio y vuelve a intentar.",
    ),
    ("Cancelado", "Cancelaste la descarga."),
)


def friendly(msg: str) -> str:
    if not msg:
        return "Algo salió mal."
    low = msg.lower()
    for needle, friendly_msg in FRIENDLY_ERRORS:
        if needle.lower() in low:
            return friendly_msg
    return msg.strip().split("\n")[0][:300]


class UserCancelledError(Exception):
    """El usuario canceló la descarga o la conversión."""


class ClipTimestampError(Exception):
    """Marcas de tiempo de recorte fuera del rango del video."""


class PlaylistNotSupportedError(Exception):
    """El enlace es una lista de reproducción y el modo elegido baja un solo video."""

    def __init__(self, title: str = ""):
        self.title = title
        nombre = f" «{title}»" if title else ""
        super().__init__(
            f"Este enlace es una lista de reproducción{nombre}. "
            "Abre un video de la lista y copia su enlace."
        )
