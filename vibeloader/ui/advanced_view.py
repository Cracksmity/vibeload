"""Vista avanzada: presets, recortes, carpeta de salida y log."""
import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..config import ADVANCED_PRESETS
from ..errors import friendly
from ..urls import find_url_in_text


class AdvancedView(QWidget):
    """Vista con todos los controles: presets, recortes, carpeta, log."""

    request_open_simple = Signal()
    request_open_folders = Signal()
    request_toggle_theme = Signal()
    request_start = Signal(str, str, str, str, str)  # url, preset, folder, start, end
    request_cancel = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._is_busy = False
        self._default_dirs = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        # Top bar
        top = QHBoxLayout()
        title = QLabel("VibeLoader · Modo avanzado")
        title.setObjectName("TitleLabel")
        top.addWidget(title)
        top.addStretch()
        self.theme_btn = QToolButton()
        self.theme_btn.setText("Tema")
        self.theme_btn.clicked.connect(self.request_toggle_theme)
        top.addWidget(self.theme_btn)
        self.simple_btn = QToolButton()
        self.simple_btn.setText("Modo simple")
        self.simple_btn.clicked.connect(self.request_open_simple)
        top.addWidget(self.simple_btn)
        layout.addLayout(top)

        sub = QLabel(
            "Descarga con yt-dlp, convierte con ffmpeg, y MP3 con metadatos. Acepta recortes."
        )
        sub.setObjectName("SubtitleLabel")
        layout.addWidget(sub)

        # URL
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("URL:"))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Pega aquí la URL de YouTube / etc.")
        url_layout.addWidget(self.url_edit, 1)
        layout.addLayout(url_layout)

        # Recortes
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("Recortar (opcional):"))
        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText("Inicio (ej. 0:45)")
        self.start_edit.setFixedWidth(130)
        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText("Fin (ej. 1:30)")
        self.end_edit.setFixedWidth(130)
        time_layout.addWidget(self.start_edit)
        time_layout.addWidget(QLabel(" a "))
        time_layout.addWidget(self.end_edit)
        time_layout.addStretch()
        layout.addLayout(time_layout)

        # Carpeta de salida
        out_layout = QHBoxLayout()
        out_layout.addWidget(QLabel("Carpeta de salida:"))
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Elige dónde guardar el archivo…")
        browse_btn = QPushButton("Examinar")
        browse_btn.setObjectName("secondary")
        browse_btn.clicked.connect(self._elegir_carpeta)
        defaults_btn = QPushButton("Carpetas…")
        defaults_btn.setObjectName("secondary")
        defaults_btn.setToolTip("Cambiar las carpetas predeterminadas de cada modo")
        defaults_btn.clicked.connect(self.request_open_folders)
        out_layout.addWidget(self.out_edit, 1)
        out_layout.addWidget(browse_btn)
        out_layout.addWidget(defaults_btn)
        layout.addLayout(out_layout)

        # Preset
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Modo:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(ADVANCED_PRESETS))
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.preset_combo, 1)
        layout.addLayout(preset_layout)

        # Acción
        action = QHBoxLayout()
        self.start_btn = QPushButton("Descargar")
        self.start_btn.clicked.connect(self._on_start)
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setObjectName("secondary")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.request_cancel)
        action.addWidget(self.start_btn)
        action.addWidget(self.cancel_btn)
        layout.addLayout(action)

        # Progreso
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Esperando…")
        layout.addWidget(self.progress)

        # Log
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Aquí aparecerán los detalles del proceso…")
        layout.addWidget(self.log_box, 1)

    # ---------- Public API ----------
    def set_default_dirs(self, dirs: dict):
        self._default_dirs = dict(dirs)
        if not self.out_edit.text().strip():
            d = self._default_dirs.get(self.preset_combo.currentText())
            if d:
                self.out_edit.setText(d)

    def set_busy(self, busy: bool):
        self._is_busy = busy
        self.start_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.url_edit.setEnabled(not busy)
        self.start_edit.setEnabled(not busy)
        self.end_edit.setEnabled(not busy)
        self.out_edit.setEnabled(not busy)
        self.preset_combo.setEnabled(not busy)
        if busy:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat("Iniciando…")

    def set_progress(self, pct: int, detail: str):
        self.progress.setRange(0, 100)
        self.progress.setValue(pct)
        self.progress.setFormat(detail or f"{pct}%")

    def append_log(self, text: str):
        self.log_box.append(text)

    def show_success(self, file_path: str):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("Listo")

    def show_error(self, msg: str):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Error")
        self.append_log("⚠ " + friendly(msg))

    def show_cancelled(self):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Cancelado")

    # ---------- Internal ----------
    def _on_preset_changed(self, modo: str):
        d = self._default_dirs.get(modo)
        if not d:
            return
        if not self.out_edit.text().strip():
            self.out_edit.setText(d)

    def _elegir_carpeta(self):
        carpeta = QFileDialog.getExistingDirectory(
            self, "Elegir carpeta de salida", self.out_edit.text() or os.path.expanduser("~")
        )
        if carpeta:
            self.out_edit.setText(carpeta)

    def _on_start(self):
        url = self.url_edit.text().strip()
        carpeta = self.out_edit.text().strip()
        preset = self.preset_combo.currentText()
        start_t = self.start_edit.text().strip()
        end_t = self.end_edit.text().strip()
        if not url:
            self.append_log("⚠️ Pega o escribe una URL.")
            return
        if not carpeta:
            self.append_log("⚠️ Elige una carpeta de salida.")
            return
        self.request_start.emit(url, preset, carpeta, start_t, end_t)

    # ---------- Drag & drop ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasText() or e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        text = ""
        if e.mimeData().hasText():
            text = e.mimeData().text()
        elif e.mimeData().hasUrls():
            urls = e.mimeData().urls()
            if urls:
                text = urls[0].toString()
        url = find_url_in_text(text) or text
        if url:
            self.url_edit.setText(url.strip())
