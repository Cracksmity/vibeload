"""Vista avanzada: presets, recortes, opciones, cola y log."""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..config import (
    ADVANCED_PRESETS,
    DEFAULT_TARGET_SIZE_MB,
    PRESET_TAMANO,
    TARGET_SIZE_CHOICES,
)
from ..errors import friendly
from ..jobs import SUBS_EMBED, SUBS_NONE, SUBS_SRT, JobOptions
from ..urls import find_url_in_text, is_http_url

COOKIE_BROWSERS = (
    ("No usar", None),
    ("Firefox (recomendado)", "firefox"),
    ("Chrome (ciérralo antes)", "chrome"),
    ("Edge (ciérralo antes)", "edge"),
    ("Brave", "brave"),
    ("Opera", "opera"),
)
SUBS_MODES = (
    ("Sin subtítulos", SUBS_NONE),
    ("Archivo .srt aparte", SUBS_SRT),
    ("Incrustados en el video", SUBS_EMBED),
)
SUBS_LANGS = (
    ("Español", ("es",)),
    ("Inglés", ("en",)),
    ("Español e inglés", ("es", "en")),
)


class AdvancedView(QWidget):
    """Vista con todos los controles: presets, recortes, carpeta, opciones, cola y log."""

    request_open_simple = Signal()
    request_open_folders = Signal()
    request_open_history = Signal()
    request_toggle_theme = Signal()
    request_start = Signal(str, str, str, str, str)  # url, preset, folder, start, end
    request_cancel = Signal()
    request_remove_queued = Signal(int)  # id del trabajo
    request_clear_queue = Signal()
    request_update_ytdlp = Signal()
    request_install_ffmpeg = Signal()
    auto_update_toggled = Signal(bool)
    options_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._is_busy = False
        self._default_dirs = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)

        # Top bar
        top = QHBoxLayout()
        title = QLabel("VibeLoader · Modo avanzado")
        title.setObjectName("TitleLabel")
        top.addWidget(title)
        top.addStretch()
        self.history_btn = QToolButton()
        self.history_btn.setText("Historial")
        self.history_btn.clicked.connect(self.request_open_history)
        top.addWidget(self.history_btn)
        self.theme_btn = QToolButton()
        self.theme_btn.setText("Tema")
        self.theme_btn.clicked.connect(self.request_toggle_theme)
        top.addWidget(self.theme_btn)
        self.simple_btn = QToolButton()
        self.simple_btn.setText("Modo simple")
        self.simple_btn.clicked.connect(self.request_open_simple)
        top.addWidget(self.simple_btn)
        layout.addLayout(top)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        row = 0

        # URL
        grid.addWidget(QLabel("URL:"), row, 0)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Pega aquí la URL (video o lista de reproducción)")
        grid.addWidget(self.url_edit, row, 1, 1, 3)
        row += 1

        # Recortes
        grid.addWidget(QLabel("Recortar:"), row, 0)
        time_layout = QHBoxLayout()
        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText("Inicio (ej. 0:45)")
        self.start_edit.setFixedWidth(130)
        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText("Fin (ej. 1:30)")
        self.end_edit.setFixedWidth(130)
        time_layout.addWidget(self.start_edit)
        time_layout.addWidget(QLabel(" a "))
        time_layout.addWidget(self.end_edit)
        time_layout.addWidget(QLabel("(opcional)"))
        time_layout.addStretch()
        grid.addLayout(time_layout, row, 1, 1, 3)
        row += 1

        # Carpeta de salida
        grid.addWidget(QLabel("Carpeta:"), row, 0)
        out_layout = QHBoxLayout()
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
        grid.addLayout(out_layout, row, 1, 1, 3)
        row += 1

        # Modo + tamaño
        grid.addWidget(QLabel("Modo:"), row, 0)
        preset_layout = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(ADVANCED_PRESETS))
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.preset_combo, 1)
        self.size_label = QLabel("Peso máx. (MB):")
        self.size_combo = QComboBox()
        self.size_combo.setEditable(True)
        self.size_combo.addItems(list(TARGET_SIZE_CHOICES))
        self.size_combo.setCurrentText(f"{DEFAULT_TARGET_SIZE_MB:g}")
        self.size_combo.setFixedWidth(100)
        self.size_combo.setToolTip("WhatsApp: hasta 2 GB · Discord gratis: 10 MB · correo: ~25 MB")
        preset_layout.addWidget(self.size_label)
        preset_layout.addWidget(self.size_combo)
        grid.addLayout(preset_layout, row, 1, 1, 3)
        row += 1

        # Codificador + cookies
        grid.addWidget(QLabel("Codificador:"), row, 0)
        self.encoder_combo = QComboBox()
        self.encoder_combo.addItem("Automático (tarjeta de video si se puede)", "auto")
        self.encoder_combo.addItem("Solo CPU (más lento, archivos algo más chicos)", "cpu")
        grid.addWidget(self.encoder_combo, row, 1)
        grid.addWidget(QLabel("Cookies del navegador:"), row, 2)
        self.cookies_combo = QComboBox()
        for label, value in COOKIE_BROWSERS:
            self.cookies_combo.addItem(label, value)
        self.cookies_combo.setToolTip(
            "Usa tu sesión del navegador para videos con restricción de edad o cuando "
            "YouTube pide confirmar que no eres un bot. Chrome y Edge bloquean sus "
            "cookies mientras están abiertos: ciérralos antes de descargar."
        )
        grid.addWidget(self.cookies_combo, row, 3)
        row += 1

        # Subtítulos
        grid.addWidget(QLabel("Subtítulos:"), row, 0)
        self.subs_mode_combo = QComboBox()
        for label, value in SUBS_MODES:
            self.subs_mode_combo.addItem(label, value)
        grid.addWidget(self.subs_mode_combo, row, 1)
        grid.addWidget(QLabel("Idioma:"), row, 2)
        self.subs_lang_combo = QComboBox()
        for label, value in SUBS_LANGS:
            self.subs_lang_combo.addItem(label, value)
        grid.addWidget(self.subs_lang_combo, row, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)

        for combo in (self.encoder_combo, self.cookies_combo, self.subs_mode_combo, self.subs_lang_combo):
            combo.currentIndexChanged.connect(lambda _i: self.options_changed.emit())
        self.subs_mode_combo.currentIndexChanged.connect(self._update_subs_enabled)
        self._update_subs_enabled()
        self._update_size_visibility(self.preset_combo.currentText())

        # Acción
        action = QHBoxLayout()
        self.start_btn = QPushButton("Descargar")
        self.start_btn.clicked.connect(self._on_start)
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setObjectName("secondary")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setToolTip("Cancela la descarga actual y vacía la cola")
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

        # Herramientas
        tools_row = QHBoxLayout()
        self.update_btn = QPushButton("Actualizar yt-dlp")
        self.update_btn.setObjectName("secondary")
        self.update_btn.setToolTip("Descarga la versión más nueva (YouTube cambia seguido)")
        self.update_btn.clicked.connect(self.request_update_ytdlp)
        self.ffmpeg_btn = QPushButton("Descargar ffmpeg")
        self.ffmpeg_btn.setObjectName("secondary")
        self.ffmpeg_btn.setToolTip("Instala ffmpeg en la carpeta de VibeLoader (no toca el sistema)")
        self.ffmpeg_btn.clicked.connect(self.request_install_ffmpeg)
        self.auto_update_chk = QCheckBox("Buscar actualizaciones de yt-dlp al iniciar")
        self.auto_update_chk.toggled.connect(self.auto_update_toggled)
        tools_row.addWidget(self.update_btn)
        tools_row.addWidget(self.ffmpeg_btn)
        tools_row.addWidget(self.auto_update_chk)
        tools_row.addStretch()
        layout.addLayout(tools_row)

        # Registro y cola en pestañas (ahorra espacio vertical)
        self.tabs = QTabWidget()
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Aquí aparecerán los detalles del proceso…")
        self.tabs.addTab(self.log_box, "Registro")

        queue_page = QWidget()
        ql = QVBoxLayout(queue_page)
        ql.setContentsMargins(0, 6, 0, 0)
        self.queue_list = QListWidget()
        self.queue_list.itemSelectionChanged.connect(self._update_queue_buttons)
        ql.addWidget(self.queue_list, 1)
        qb = QHBoxLayout()
        self.remove_queued_btn = QPushButton("Quitar de la cola")
        self.remove_queued_btn.setObjectName("secondary")
        self.remove_queued_btn.clicked.connect(self._on_remove_queued)
        self.clear_queue_btn = QPushButton("Vaciar cola")
        self.clear_queue_btn.setObjectName("secondary")
        self.clear_queue_btn.clicked.connect(self.request_clear_queue)
        qb.addWidget(self.remove_queued_btn)
        qb.addWidget(self.clear_queue_btn)
        qb.addStretch()
        ql.addLayout(qb)
        self.tabs.addTab(queue_page, "Cola")
        layout.addWidget(self.tabs, 1)
        self.set_queue([], None)

    # ---------- Public API ----------
    def set_default_dirs(self, dirs: dict):
        self._default_dirs = dict(dirs)
        if not self.out_edit.text().strip():
            d = self._default_dirs.get(self.preset_combo.currentText())
            if d:
                self.out_edit.setText(d)

    def encoder_mode(self) -> str:
        return self.encoder_combo.currentData() or "auto"

    def target_size_mb(self) -> float | None:
        txt = self.size_combo.currentText().strip().lower().replace("mb", "").replace(",", ".")
        try:
            v = float(txt)
        except ValueError:
            return None
        return v if v > 0 else None

    def job_options(self) -> JobOptions:
        return JobOptions(
            encoder_mode=self.encoder_mode(),
            target_mb=self.target_size_mb() or DEFAULT_TARGET_SIZE_MB,
            cookies_browser=self.cookies_combo.currentData(),
            subs_mode=self.subs_mode_combo.currentData() or SUBS_NONE,
            subs_langs=tuple(self.subs_lang_combo.currentData() or ("es",)),
        )

    def save_options(self, settings):
        settings.setValue("encoder_mode", self.encoder_mode())
        settings.setValue("cookies_browser", self.cookies_combo.currentData() or "")
        settings.setValue("subs_mode", self.subs_mode_combo.currentData() or SUBS_NONE)
        settings.setValue("subs_langs", ",".join(self.subs_lang_combo.currentData() or ("es",)))

    def load_options(self, settings):
        def select(combo, value):
            i = combo.findData(value)
            if i >= 0:
                combo.setCurrentIndex(i)

        select(self.encoder_combo, str(settings.value("encoder_mode", "auto")))
        select(self.cookies_combo, str(settings.value("cookies_browser", "")) or None)
        select(self.subs_mode_combo, str(settings.value("subs_mode", SUBS_NONE)))
        langs = tuple(x for x in str(settings.value("subs_langs", "es")).split(",") if x)
        select(self.subs_lang_combo, langs)

    def set_busy(self, busy: bool):
        """Con un trabajo en curso se puede seguir agregando a la cola."""
        self._is_busy = busy
        self.cancel_btn.setEnabled(busy)
        self.start_btn.setText("Agregar a la cola" if busy else "Descargar")
        if busy:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat("Iniciando…")

    def set_queue(self, jobs, current):
        """Muestra el trabajo actual y los pendientes."""
        self.queue_list.clear()
        if current is not None:
            item = QListWidgetItem(f"▶ {self._job_label(current)}")
            item.setData(Qt.ItemDataRole.UserRole, None)
            self.queue_list.addItem(item)
        for job in jobs:
            item = QListWidgetItem(f"⏳ {self._job_label(job)}")
            item.setData(Qt.ItemDataRole.UserRole, job.id)
            self.queue_list.addItem(item)
        self.tabs.setTabText(1, f"Cola ({len(jobs)})" if jobs else "Cola")
        self.clear_queue_btn.setEnabled(bool(jobs))
        self._update_queue_buttons()

    @staticmethod
    def _job_label(job) -> str:
        name = job.title or job.url
        return f"{name}  ·  {job.preset}"

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
    def _update_subs_enabled(self, *_):
        self.subs_lang_combo.setEnabled(self.subs_mode_combo.currentData() != SUBS_NONE)

    def _update_queue_buttons(self):
        items = self.queue_list.selectedItems()
        self.remove_queued_btn.setEnabled(
            bool(items) and items[0].data(Qt.ItemDataRole.UserRole) is not None
        )

    def _on_remove_queued(self):
        items = self.queue_list.selectedItems()
        if items:
            job_id = items[0].data(Qt.ItemDataRole.UserRole)
            if job_id is not None:
                self.request_remove_queued.emit(int(job_id))

    def _update_size_visibility(self, modo: str):
        visible = modo == PRESET_TAMANO
        self.size_label.setVisible(visible)
        self.size_combo.setVisible(visible)

    def _on_preset_changed(self, modo: str):
        self._update_size_visibility(modo)
        d = self._default_dirs.get(modo)
        if not d:
            return
        # Cambia a la carpeta del modo si la actual está vacía o es la de otro modo
        # (no pisa una carpeta elegida a mano).
        actual = self.out_edit.text().strip()
        if not actual or actual in self._default_dirs.values():
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
        if not is_http_url(url):
            self.append_log("⚠️ Esa URL no se ve válida: debe empezar con http:// o https://")
            return
        if not carpeta:
            self.append_log("⚠️ Elige una carpeta de salida.")
            return
        if preset == PRESET_TAMANO and self.target_size_mb() is None:
            self.append_log("⚠️ Escribe un peso máximo válido en MB (por ejemplo 25).")
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
