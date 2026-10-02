"""Workers en hilos Qt: trabajo de descarga y extractor de metadatos."""
import os
import threading

from PySide6.QtCore import QObject, Signal, Slot

from .config import PRESET_CAR, PRESET_DIRECTO, PRESET_MAX, PRESET_MP3, PRESET_WHATSAPP
from .errors import ClipTimestampError, UserCancelledError
from .ffmpeg_core import run_ffmpeg_car, run_ffmpeg_whatsapp
from .thumbnails import collect_thumbnail_urls
from .utils import pick_auto_output_path
from .ytdlp_core import (
    _import_ytdlp,
    _ydl_opts_metadata_only,
    clip_range_requested,
    descargar_audio_mp3,
    descargar_video_car,
    descargar_video_directo,
    descargar_video_max_calidad,
    descargar_video_whatsapp,
    fetch_video_duration_seconds,
    validate_clip_against_duration,
)


class Worker(QObject):
    finished = Signal()
    error = Signal(str)
    log = Signal(str)
    progress = Signal(int, str)
    completed = Signal(str)

    def __init__(self, url, carpeta_salida, preset, start_time, end_time):
        super().__init__()
        self.url = url
        self.carpeta_salida = carpeta_salida
        self.preset = preset
        self.start_time = start_time
        self.end_time = end_time
        self._cancel_event = threading.Event()
        self._proc_holder = {}

    @Slot()
    def request_cancel(self):
        self._cancel_event.set()
        proc = self._proc_holder.get("p")
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    @Slot()
    def run(self):
        result_path = None
        try:
            def logger(msg):
                self.log.emit(msg)

            def emit_progress(p, msg):
                self.progress.emit(max(0, min(100, int(p))), msg)

            logger("🌐 URL: " + self.url)
            logger("📁 Carpeta: " + self.carpeta_salida)
            logger(f"🎚 Modo: {self.preset}")
            emit_progress(0, "Iniciando…")

            if clip_range_requested(self.start_time, self.end_time):
                duration = fetch_video_duration_seconds(self.url)
                if duration is None:
                    raise ClipTimestampError(
                        "No se pudo obtener la duración del video (puede ser una transmisión en "
                        "vivo o el sitio no publica esa información). No se puede recortar por "
                        "tiempo sin conocer la duración."
                    )
                validate_clip_against_duration(
                    self.start_time, self.end_time, duration
                )

            if self.preset == PRESET_WHATSAPP:
                input_file, info = descargar_video_whatsapp(
                    self.url,
                    self.carpeta_salida,
                    self.start_time,
                    self.end_time,
                    logger=logger,
                    cancel_event=self._cancel_event,
                    emit_progress=emit_progress,
                )
                vid = str(info.get("id") or "video").strip()
                output_file = os.path.join(self.carpeta_salida, f"{vid}.mp4")
                run_ffmpeg_whatsapp(
                    input_file,
                    output_file,
                    logger,
                    emit_progress,
                    self._cancel_event,
                    self._proc_holder,
                    73,
                    99,
                )
                _safe_remove(input_file, logger)
                result_path = output_file
                logger("✨ Listo. Compatible con WhatsApp.")
                emit_progress(100, "Listo")

            elif self.preset == PRESET_CAR:
                input_file, info = descargar_video_car(
                    self.url,
                    self.carpeta_salida,
                    self.start_time,
                    self.end_time,
                    logger=logger,
                    cancel_event=self._cancel_event,
                    emit_progress=emit_progress,
                )
                title = (info.get("title") or "video").strip()
                vid = str(info.get("id") or "unknown").strip()
                output_file = pick_auto_output_path(
                    self.carpeta_salida, title, vid, input_file
                )
                run_ffmpeg_car(
                    input_file,
                    output_file,
                    logger,
                    emit_progress,
                    self._cancel_event,
                    self._proc_holder,
                    73,
                    99,
                )
                _safe_remove(input_file, logger)
                result_path = output_file
                logger("✨ Listo. Compatible con autoestéreos.")
                emit_progress(100, "Listo")

            elif self.preset == PRESET_MAX:
                fname = descargar_video_max_calidad(
                    self.url,
                    self.carpeta_salida,
                    self.start_time,
                    self.end_time,
                    logger=logger,
                    cancel_event=self._cancel_event,
                    emit_progress=emit_progress,
                )
                result_path = fname
                emit_progress(100, "Listo")
                logger("✨ Listo. Video descargado en la mejor calidad.")

            elif self.preset == PRESET_DIRECTO:
                fname = descargar_video_directo(
                    self.url,
                    self.carpeta_salida,
                    self.start_time,
                    self.end_time,
                    logger=logger,
                    cancel_event=self._cancel_event,
                    emit_progress=emit_progress,
                )
                result_path = fname
                emit_progress(100, "Listo")
                logger("✨ Listo. Video descargado directamente sin recodificar.")

            elif self.preset == PRESET_MP3:
                fname = descargar_audio_mp3(
                    self.url,
                    self.carpeta_salida,
                    self.start_time,
                    self.end_time,
                    logger=logger,
                    cancel_event=self._cancel_event,
                    emit_progress=emit_progress,
                )
                result_path = fname
                emit_progress(100, "Listo")
                logger("✨ Listo. Audio MP3 listo.")

            else:
                raise ValueError(f"Preset no reconocido: {self.preset}")

            if result_path:
                self.completed.emit(result_path)

        except UserCancelledError as e:
            self.log.emit("⏹️ " + str(e))
            self.progress.emit(0, "Cancelado")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


def _safe_remove(path, logger):
    try:
        if os.path.exists(path):
            os.remove(path)
            logger(f"🧹 Archivo intermedio borrado: {path}")
    except OSError as e:
        logger(f"⚠️ No se pudo borrar {path}: {e}")


# ============================================================
# METADATA FETCHER
# ============================================================


class MetadataFetcher(QObject):
    """Vive en su propio QThread; extrae info sin descargar."""

    fetched = Signal(dict, int)
    failed = Signal(str, int)

    @Slot(str, int)
    def fetch(self, url: str, token: int):
        if not url:
            return
        try:
            YoutubeDL, _ = _import_ytdlp()
            ydl_opts = _ydl_opts_metadata_only(url)
            try:
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
            except Exception as e:
                msg = str(e).lower()
                if ("impersonate target" in msg or "impersonate" in msg) and "impersonate" in ydl_opts:
                    self.log.emit("⚠️ Impersonate no disponible en esta build; reintentando sin impersonate…")
                    ydl_opts2 = dict(ydl_opts)
                    ydl_opts2.pop("impersonate", None)
                    with YoutubeDL(ydl_opts2) as ydl:
                        info = ydl.extract_info(url, download=False)
                else:
                    raise
        except Exception as e:
            self.failed.emit(str(e), token)
            return
        data = {
            "title": info.get("title") or "",
            "channel": info.get("channel") or info.get("uploader") or "",
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail") or "",
            "thumbnail_urls": collect_thumbnail_urls(info),
            "url": url,
        }
        self.fetched.emit(data, token)
