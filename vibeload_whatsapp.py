import os
import sys
import subprocess

from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QFileDialog,
    QTextEdit, QProgressBar, QComboBox
)

from yt_dlp import YoutubeDL


# ---------- LÓGICA DE DESCARGA Y CONVERSIÓN ----------

def descargar_video_whatsapp(url, carpeta_salida, logger=print):
    """
    Descarga el video usando yt_dlp y regresa la ruta del archivo resultante.
    Pensado para luego pasarlo por HandBrake y hacerlo más compatible.
    """
    logger("🎬 Iniciando descarga (modo WhatsApp) con yt-dlp...")
    os.makedirs(carpeta_salida, exist_ok=True)

    ydl_opts = {
        "outtmpl": os.path.join(carpeta_salida, "%(title)s.%(ext)s"),
        # Mejor video+audio fusionado a mp4
        "format": "bv*+ba/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    base, ext = os.path.splitext(filename)
    mp4_candidate = base + ".mp4"
    if os.path.exists(mp4_candidate):
        final_path = mp4_candidate
    else:
        final_path = filename

    logger(f"✅ Descarga terminada (WhatsApp base): {final_path}")
    return final_path


def descargar_video_max_calidad(url, carpeta_salida, logger=print):
    """
    Descarga el video en la mejor calidad disponible.
    NO se recomprime: ideal para ver en PC / TV, no necesariamente para WhatsApp.
    """
    logger("🎥 Iniciando descarga en máxima calidad con yt-dlp...")
    os.makedirs(carpeta_salida, exist_ok=True)

    ydl_opts = {
        "outtmpl": os.path.join(carpeta_salida, "%(title)s.%(ext)s"),
        # Máxima calidad posible (vídeo + audio)
        "format": "bv*+ba/bestvideo+bestaudio/best",
        "noplaylist": True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    logger(f"✅ Descarga en máxima calidad terminada: {filename}")
    return filename


def descargar_audio_mp3(url, carpeta_salida, logger=print):
    logger("🎧 Iniciando descarga de solo audio (MP3) con metadatos + cover...")
    os.makedirs(carpeta_salida, exist_ok=True)

    ydl_opts = {
        "outtmpl": os.path.join(carpeta_salida, "%(title)s.%(ext)s"),
        "format": "bestaudio/best",
        "noplaylist": True,
        "writethumbnail": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            },
            {"key": "FFmpegMetadata"},
            {
                "key": "FFmpegThumbnailsConvertor",
                "format": "jpg",
            },
            {"key": "EmbedThumbnail"},
        ],
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    base, _ = os.path.splitext(filename)
    mp3_file = base + ".mp3"

    # 🧹 LIMPIEZA: borrar original + miniaturas
    posibles_sobrantes = [
        filename,              # audio original (webm, m4a, etc.)
        base + ".webp",        # miniatura original
        base + ".jpg",         # miniatura convertida
    ]


    for f in posibles_sobrantes:
        if f.endswith(".mp3"):
            continue
        if os.path.exists(f):
            try:
                os.remove(f)
                logger(f"🧹 Borrado archivo sobrante: {f}")
            except Exception as e:
                logger(f"⚠️ No se pudo borrar {f}: {e}")

    logger(f"✅ Audio MP3 listo (solo el bueno): {mp3_file}")
    return mp3_file


def convertir_con_handbrake(input_file, output_file, logger=print):
    """
    Convierte el archivo a un MP4 compatible usando HandBrakeCLI.
    Preset simple para algo tipo 'WhatsApp friendly'.
    """
    logger("🔥 Iniciando conversión con HandBrakeCLI...")

    # Si usas ruta absoluta, cámbiala aquí:
    # HANDBRAKE_CLI = r"C:\Tools\HandBrakeCLI\HandBrakeCLI.exe"
    # cmd = [HANDBRAKE_CLI, ...]
    cmd = [
        "HandBrakeCLI",
        "-i", input_file,
        "-o", output_file,
        # Vídeo
        "-e", "x264",        # codec de video H.264
        "-q", "22",          # calidad (20~24 está decente)
        "--optimize",        # para mejor compatibilidad/stream
        # Audio
        "-E", "av_aac",      # codec de audio AAC
        "-B", "128",         # bitrate de audio
        # Ejemplo para limitar resolución si quieres:
        # "--maxWidth", "1280",
        # "--maxHeight", "720",
    ]

    try:
        subprocess.run(cmd, check=True)
        logger(f"✅ Conversión terminada: {output_file}")
    except FileNotFoundError:
        logger("❌ Error: No se encontró 'HandBrakeCLI'. "
               "Asegúrate de tener instalado HandBrakeCLI y que el comando funcione en tu terminal.")
        raise
    except subprocess.CalledProcessError as e:
        logger(f"❌ Error al ejecutar HandBrakeCLI: {e}")
        raise


# ---------- WORKER EN HILO SEPARADO ----------

class Worker(QObject):
    finished = Signal()
    error = Signal(str)
    log = Signal(str)

    def __init__(self, url, carpeta_salida, preset):
        super().__init__()
        self.url = url
        self.carpeta_salida = carpeta_salida
        self.preset = preset

    @Slot()
    def run(self):
        try:
            def logger(msg):
                self.log.emit(msg)

            logger("🌐 URL recibida: " + self.url)
            logger("📁 Carpeta de salida: " + self.carpeta_salida)
            logger(f"🎚 Preset seleccionado: {self.preset}")

            if self.preset == "WhatsApp 720p":
                logger("🎯 Modo: WhatsApp 720p (descarga + conversión).")
                # 1) Descargar base mp4
                input_file = descargar_video_whatsapp(self.url, self.carpeta_salida, logger=logger)
                # 2) Definir salida convertida
                base, _ = os.path.splitext(input_file)
                output_file = base + "_whatsapp.mp4"
                # 3) Convertir con HandBrake
                convertir_con_handbrake(input_file, output_file, logger=logger)
                # 🔥 Borrar el archivo original

                try:
                    if os.path.exists(input_file):
                        os.remove(input_file)
                        logger(f"🧹 Archivo original borrado: {input_file}")
                except Exception as e:
                    logger(f"⚠️ No se pudo borrar el archivo original: {e}")
                logger("✨ Todo listo. Debería ser compatible con WhatsApp.")

            elif self.preset == "Máxima calidad (video)":
                logger("🎯 Modo: Máxima calidad (solo descarga, sin recomprimir).")
                descargar_video_max_calidad(self.url, self.carpeta_salida, logger=logger)
                logger("✨ Listo. Video descargado en la mejor calidad disponible.")

            elif self.preset == "Solo audio (MP3)":
                logger("🎯 Modo: Solo audio (MP3).")
                descargar_audio_mp3(self.url, self.carpeta_salida, logger=logger)
                logger("✨ Listo. Audio MP3 descargado.")

            else:
                logger("⚠️ Preset no reconocido, usando modo WhatsApp por defecto.")
                input_file = descargar_video_whatsapp(self.url, self.carpeta_salida, logger=logger)
                base, _ = os.path.splitext(input_file)
                output_file = base + "_whatsapp.mp4"
                convertir_con_handbrake(input_file, output_file, logger=logger)
                logger("✨ Todo listo (modo por defecto WhatsApp).")

        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


# ---------- INTERFAZ GRÁFICA ----------

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("VibeLoader ✨ (yt-dlp + HandBrake)")
        self.setMinimumSize(700, 500)
        self._build_ui()
        self._apply_styles()

        self.thread = None
        self.worker = None

    def _build_ui(self):
        layout = QVBoxLayout()

        # Título
        title = QLabel("VibeLoader ✨")
        subtitle = QLabel("Descarga con yt-dlp y convierte con HandBrake / MP3 con la vibra correcta.")
        title.setObjectName("TitleLabel")
        subtitle.setObjectName("SubtitleLabel")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        # Campo URL
        url_layout = QHBoxLayout()
        url_label = QLabel("URL del video:")
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Pega aquí la URL de YouTube / etc...")
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_edit)

        # Carpeta salida
        out_layout = QHBoxLayout()
        out_label = QLabel("Carpeta de salida:")
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Elige dónde guardar el archivo...")
        browse_btn = QPushButton("Examinar")
        browse_btn.clicked.connect(self.elegir_carpeta)
        out_layout.addWidget(out_label)
        out_layout.addWidget(self.out_edit)
        out_layout.addWidget(browse_btn)

        # Preset
        preset_layout = QHBoxLayout()
        preset_label = QLabel("Modo:")
        self.preset_combo = QComboBox()
        self.preset_combo.addItems([
            "WhatsApp 720p",
            "Máxima calidad (video)",
            "Solo audio (MP3)"
        ])
        preset_layout.addWidget(preset_label)
        preset_layout.addWidget(self.preset_combo)

        # Botón de acción
        self.start_btn = QPushButton("Descargar 🚀")
        self.start_btn.clicked.connect(self.iniciar_proceso)

        # Barra de progreso
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFormat("Esperando…")
        self.progress.setValue(0)

        # Área de logs
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Aquí irán apareciendo los logs con la vibra del proceso...")

        layout.addLayout(url_layout)
        layout.addLayout(out_layout)
        layout.addLayout(preset_layout)
        layout.addWidget(self.start_btn)
        layout.addWidget(self.progress)
        layout.addWidget(self.log_box)

        self.setLayout(layout)

    def _apply_styles(self):
        # Tema oscuro sencillo con algo de vibra
        self.setStyleSheet("""
            QWidget {
                background-color: #101018;
                color: #f5f5f5;
                font-family: Segoe UI, sans-serif;
                font-size: 10pt;
            }
            QLineEdit, QTextEdit, QComboBox {
                background-color: #181822;
                border: 1px solid #303040;
                border-radius: 6px;
                padding: 4px 6px;
                selection-background-color: #6c5ce7;
            }
            QPushButton {
                background-color: #6c5ce7;
                border-radius: 8px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #7f6cff;
            }
            QPushButton:disabled {
                background-color: #444;
                color: #999;
            }
            QProgressBar {
                background-color: #181822;
                border: 1px solid #303040;
                border-radius: 6px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #00cec9;
                border-radius: 6px;
            }
            #TitleLabel {
                font-size: 20pt;
                font-weight: bold;
                color: #ffeaa7;
            }
            #SubtitleLabel {
                font-size: 9pt;
                color: #b2bec3;
            }
        """)

    def log(self, text):
        self.log_box.append(text)

    def elegir_carpeta(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Elige carpeta de salida")
        if carpeta:
            self.out_edit.setText(carpeta)

    def iniciar_proceso(self):
        url = self.url_edit.text().strip()
        carpeta = self.out_edit.text().strip()
        preset = self.preset_combo.currentText()

        if not url:
            self.log("⚠️ Por favor, escribe/pega una URL.")
            return

        if not carpeta:
            self.log("⚠️ Por favor, elige una carpeta de salida.")
            return

        # Deshabilitar UI mientras trabaja
        self.start_btn.setEnabled(False)
        self.progress.setRange(0, 0)  # modo indeterminado
        self.progress.setFormat("Trabajando...")

        # Crear worker en un hilo
        self.thread = QThread()
        self.worker = Worker(url, carpeta, preset)
        self.worker.moveToThread(self.thread)

        # Conexiones
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.log)
        self.worker.error.connect(self.on_error)
        self.worker.finished.connect(self.on_finished)

        # Limpieza del hilo
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()
        self.log("🚀 Proceso lanzado en segundo plano...")

    def on_error(self, msg):
        self.log("⚠️ Ocurrió un error:\n" + msg)

    def on_finished(self):
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.setFormat("Listo ✨")
        self.start_btn.setEnabled(True)
        self.log("🏁 Proceso finalizado.")
        self.log_box.moveCursor(self.log_box.textCursor().End)


# ---------- MAIN ----------

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
