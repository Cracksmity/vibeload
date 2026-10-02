"""Vista avanzada: una fila de mando, opciones como chips y la cola como protagonista."""
import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..browsers import browser_display_name
from ..config import (
    ADVANCED_PRESETS,
    DEFAULT_TARGET_SIZE_MB,
    PRESET_MAX,
    PRESET_TAMANO,
    TARGET_SIZE_CHOICES,
    preset_label,
)
from ..errors import friendly
from ..jobs import PHASE_CONVERTING, PHASE_DOWNLOADING, SUBS_EMBED, SUBS_NONE, SUBS_SRT, JobOptions
from ..urls import find_url_in_text, is_http_url
from .widgets import Chip, ElidedLabel, FlowLayout, Popover, repolish

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
ENCODERS = (
    ("GPU automática (más rápido)", "auto"),
    ("Solo CPU (más lento, archivos algo más chicos)", "cpu"),
)


def format_speed(bps: float | None) -> str:
    if not bps:
        return ""
    mb = bps / 1_000_000
    return f"{mb:.1f} MB/s".replace(".", ",") if mb < 100 else f"{mb:.0f} MB/s"


def format_clock(seconds: float | None) -> str:
    if seconds is None:
        return ""
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _combo(items) -> QComboBox:
    c = QComboBox()
    for label, value in items:
        c.addItem(label, value)
    return c


def _select(combo: QComboBox, value):
    i = combo.findData(value)
    if i >= 0:
        combo.setCurrentIndex(i)


class QueueRow(QFrame):
    """Una fila de la cola: título, formato, fase, progreso y su acción."""

    action = Signal(int, str)  # id del trabajo, acción (cancel | remove | retry | open)

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.setObjectName("QueueRow")
        self.job_id = job.id
        grid = QGridLayout(self)
        grid.setContentsMargins(10, 8, 6, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(2)
        self.title = ElidedLabel("")
        self.title.setObjectName("RowTitle")
        self.meta = ElidedLabel("")
        self.meta.setObjectName("RowMeta")
        grid.addWidget(self.title, 0, 0)
        grid.addWidget(self.meta, 1, 0)
        status_row = QHBoxLayout()
        self.phase = QLabel("")
        self.phase.setObjectName("RowStatus")
        self.numbers = QLabel("")
        self.numbers.setObjectName("RowStatus")
        status_row.addWidget(self.phase)
        status_row.addStretch()
        status_row.addWidget(self.numbers)
        grid.addLayout(status_row, 0, 1)
        self.bar = QProgressBar()
        self.bar.setObjectName("thin")
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        grid.addWidget(self.bar, 1, 1)
        self.btn = QToolButton()
        self.btn.setObjectName("RowAction")
        self.btn.clicked.connect(self._on_click)
        grid.addWidget(self.btn, 0, 2, 2, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.setColumnMinimumWidth(1, 200)
        self._action = ""
        self.update_from(job)

    def update_from(self, job):
        self.title.setText(job.title or job.url)
        trim = ""
        if job.start or job.end:
            trim = f"{job.start or '0:00'}–{job.end or 'fin'}"
        folder = os.path.basename(os.path.normpath(job.folder)) if job.folder else ""
        self.meta.setText(" · ".join(x for x in (preset_label(job.preset), trim, folder) if x))
        st = job.status
        kind = ""
        self.bar.setVisible(st in ("descargando", "en cola"))
        self.setProperty("active", "true" if st == "descargando" else "false")
        if st == "descargando":
            info = job.progress
            pct = info.pct if info else 0
            self.bar.setValue(pct)
            if info is None:
                phase = "Preparando"
            elif info.phase == PHASE_CONVERTING:
                phase = "Convirtiendo"
            elif info.phase == PHASE_DOWNLOADING:
                phase = "Descargando"
            else:
                phase = "Preparando"
            self.phase.setText(phase)
            extra = format_speed(info.speed) if info else ""
            eta = format_clock(info.eta) if info and info.eta is not None else ""
            self.numbers.setText("  ".join(x for x in (f"{pct} %", extra, eta) if x))
            self.numbers.setToolTip(info.text if info else "")
            self._set_action("cancel", "✕", "Cancelar esta descarga")
        elif st == "en cola":
            self.bar.setValue(0)
            self.phase.setText("En espera")
            self.numbers.setText("")
            self._set_action("remove", "✕", "Quitar de la cola")
        elif st == "listo":
            kind = "ok"
            self.phase.setText("✓ Listo")
            self.numbers.setText("")
            self._set_action("open", "Abrir", job.result_path)
        elif st == "lista":
            self.phase.setText("Lista de reproducción: elige los videos")
            self.numbers.setText("")
            self._set_action("", "", "")
        else:  # error | cancelado
            kind = "error"
            text = "Cancelado" if st == "cancelado" else friendly(job.error)
            self.phase.setText(text)
            self.phase.setToolTip(job.error)
            self.numbers.setText("")
            self._set_action("retry", "Reintentar", "Volver a intentarlo")
        for lab in (self.phase, self.numbers):
            lab.setProperty("kind", kind)
            repolish(lab)
        repolish(self)

    def _set_action(self, action, text, tip):
        self._action = action
        self.btn.setVisible(bool(action))
        self.btn.setText(text)
        self.btn.setToolTip(tip)

    def _on_click(self):
        if self._action:
            self.action.emit(self.job_id, self._action)


class AdvancedView(QWidget):
    request_open_folders = Signal()
    request_start = Signal(str, str, str, str, str)  # url, preset, folder, start, end
    request_job_action = Signal(int, str)  # id, cancel | remove | retry | open
    request_cancel_all = Signal()
    request_clear_finished = Signal()
    options_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AdvancedView")
        self.setAcceptDrops(True)
        self._is_busy = False
        self._default_dirs = {}
        self._folder = ""
        self._folder_custom = False
        self._rows = {}
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QVBoxLayout()
        top.setContentsMargins(16, 12, 16, 10)
        top.setSpacing(10)
        root.addLayout(top)

        # Enlace + acción principal
        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Pega el enlace (video o lista de reproducción)")
        self.url_edit.setAccessibleName("Enlace")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.returnPressed.connect(self._on_start)
        url_row.addWidget(self.url_edit, 1)
        paste = QPushButton("Pegar")
        paste.setObjectName("secondary")
        paste.clicked.connect(self._do_paste)
        url_row.addWidget(paste)
        self.start_btn = QPushButton("Descargar")
        self.start_btn.setToolTip("Ctrl+Enter")
        self.start_btn.clicked.connect(self._on_start)
        url_row.addWidget(self.start_btn)
        top.addLayout(url_row)

        # Campos: formato, peso, carpeta
        fields = QHBoxLayout()
        fields.setSpacing(8)
        fmt = QFrame()
        fmt.setObjectName("Field")
        fl = QHBoxLayout(fmt)
        fl.setContentsMargins(10, 0, 2, 0)
        fl.setSpacing(2)
        lab = QLabel("Formato")
        lab.setObjectName("FieldLabel")
        fl.addWidget(lab)
        self.preset_combo = QComboBox()
        self.preset_combo.setObjectName("FieldCombo")
        for p in ADVANCED_PRESETS:
            self.preset_combo.addItem(preset_label(p), p)
        _select(self.preset_combo, PRESET_MAX)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        fl.addWidget(self.preset_combo)
        fields.addWidget(fmt)

        self.size_field = QFrame()
        self.size_field.setObjectName("Field")
        sl = QHBoxLayout(self.size_field)
        sl.setContentsMargins(10, 0, 2, 0)
        sl.setSpacing(2)
        slab = QLabel("Peso ≤")
        slab.setObjectName("FieldLabel")
        sl.addWidget(slab)
        self.size_combo = QComboBox()
        self.size_combo.setObjectName("FieldCombo")
        self.size_combo.setEditable(True)
        self.size_combo.addItems(list(TARGET_SIZE_CHOICES))
        self.size_combo.setCurrentText(f"{DEFAULT_TARGET_SIZE_MB:g}")
        self.size_combo.setFixedWidth(80)
        self.size_combo.setToolTip("En MB. WhatsApp: hasta 2 GB · Discord gratis: 10 MB · correo: ~25 MB")
        sl.addWidget(self.size_combo)
        mb = QLabel("MB")
        mb.setObjectName("FieldLabel")
        sl.addWidget(mb)
        fields.addWidget(self.size_field)

        self.folder_btn = QPushButton()
        self.folder_btn.setObjectName("FolderButton")
        self.folder_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        menu = QMenu(self.folder_btn)
        menu.addAction("Elegir otra carpeta…", self._choose_folder)
        self._reset_folder_act = menu.addAction("Usar la carpeta de este formato", self._reset_folder)
        menu.addAction("Abrir esta carpeta", self._open_folder)
        menu.addSeparator()
        menu.addAction("Carpetas por formato…", self.request_open_folders)
        self.folder_btn.setMenu(menu)
        fields.addWidget(self.folder_btn, 1)
        top.addLayout(fields)

        # Chips
        chips_host = QWidget()
        chips = FlowLayout(chips_host, spacing=8)
        self._build_chips(chips)
        top.addWidget(chips_host)

        # Cola y registro
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        queue_page = QWidget()
        ql = QVBoxLayout(queue_page)
        ql.setContentsMargins(8, 6, 8, 0)
        self.queue_list = QListWidget()
        self.queue_list.setObjectName("Queue")
        self.queue_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.queue_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        ql.addWidget(self.queue_list, 1)
        self.empty_label = QLabel("La cola está vacía. Pega un enlace y pulsa Descargar.")
        self.empty_label.setObjectName("EmptyQueue")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ql.addWidget(self.empty_label, 1)
        self.tabs.addTab(queue_page, "Cola")
        self.log_box = QTextEdit()
        self.log_box.setObjectName("Log")
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Aquí aparecen los detalles técnicos de cada descarga.")
        log_page = QWidget()
        lgl = QVBoxLayout(log_page)
        lgl.setContentsMargins(16, 0, 16, 0)
        lgl.addWidget(self.log_box)
        self.tabs.addTab(log_page, "Registro")

        corner = QWidget()
        cl = QHBoxLayout(corner)
        cl.setContentsMargins(0, 0, 8, 0)
        cl.setSpacing(2)
        self.cancel_all_btn = QPushButton("Cancelar todo")
        self.cancel_all_btn.setObjectName("ghost")
        self.cancel_all_btn.setToolTip("Cancela la descarga actual y vacía la cola")
        self.cancel_all_btn.clicked.connect(self.request_cancel_all)
        self.clear_done_btn = QPushButton("Vaciar terminados")
        self.clear_done_btn.setObjectName("ghost")
        self.clear_done_btn.clicked.connect(self.request_clear_finished)
        cl.addWidget(self.cancel_all_btn)
        cl.addWidget(self.clear_done_btn)
        self.tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)
        tabs_wrap = QVBoxLayout()
        tabs_wrap.setContentsMargins(8, 0, 0, 0)
        tabs_wrap.addWidget(self.tabs)
        root.addLayout(tabs_wrap, 1)

        # Pie
        foot = QFrame()
        foot.setObjectName("Footer")
        foot.setFixedHeight(28)
        fl2 = QHBoxLayout(foot)
        fl2.setContentsMargins(16, 0, 16, 0)
        self.tools_label = QLabel("")
        self.tools_label.setObjectName("FooterText")
        self.queue_label = QLabel("")
        self.queue_label.setObjectName("FooterText")
        fl2.addWidget(self.tools_label)
        fl2.addStretch()
        fl2.addWidget(self.queue_label)
        root.addWidget(foot)

        QShortcut(QKeySequence("Ctrl+Return"), self, self._on_start)
        QShortcut(QKeySequence("Ctrl+Enter"), self, self._on_start)
        self._on_preset_changed()
        self.set_queue([])

    def _build_chips(self, flow):
        # Recortar
        pop = Popover(self)
        title = QLabel("Recortar")
        title.setObjectName("PopoverTitle")
        pop.content.addWidget(title)
        row = QHBoxLayout()
        self.start_edit = QLineEdit()
        self.start_edit.setPlaceholderText("Desde 0:45")
        self.end_edit = QLineEdit()
        self.end_edit.setPlaceholderText("Hasta 1:30")
        for e in (self.start_edit, self.end_edit):
            e.setFixedWidth(110)
            e.textChanged.connect(self._refresh_chips)
        row.addWidget(self.start_edit)
        row.addWidget(QLabel("→"))
        row.addWidget(self.end_edit)
        pop.content.addLayout(row)
        hint = QLabel("Minutos:segundos o h:mm:ss. Deja uno vacío para ir desde el inicio o hasta el final.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        hint.setFixedWidth(260)
        pop.content.addWidget(hint)
        self.trim_chip = Chip("✂ Recortar", pop)
        self.trim_chip.cleared.connect(self._clear_trim)
        flow.addWidget(self.trim_chip)

        # Subtítulos
        pop = Popover(self)
        t = QLabel("Subtítulos")
        t.setObjectName("PopoverTitle")
        pop.content.addWidget(t)
        self.subs_mode_combo = _combo(SUBS_MODES)
        self.subs_lang_combo = _combo(SUBS_LANGS)
        pop.content.addWidget(self.subs_mode_combo)
        pop.content.addWidget(self.subs_lang_combo)
        self.subs_chip = Chip("CC Subtítulos", pop)
        self.subs_chip.cleared.connect(lambda: _select(self.subs_mode_combo, SUBS_NONE))
        flow.addWidget(self.subs_chip)

        # Sesión del navegador
        pop = Popover(self)
        t = QLabel("Sesión del navegador")
        t.setObjectName("PopoverTitle")
        pop.content.addWidget(t)
        self.cookies_combo = _combo(COOKIE_BROWSERS)
        pop.content.addWidget(self.cookies_combo)
        info = QLabel(
            "Para videos con restricción de edad o cuando YouTube pide confirmar que no "
            "eres un robot. Chrome y Edge bloquean su sesión mientras están abiertos."
        )
        info.setObjectName("Hint")
        info.setWordWrap(True)
        info.setFixedWidth(280)
        pop.content.addWidget(info)
        self.cookies_chip = Chip("Sesión del navegador", pop)
        self.cookies_chip.cleared.connect(lambda: _select(self.cookies_combo, None))
        flow.addWidget(self.cookies_chip)

        # Aceleración
        pop = Popover(self)
        t = QLabel("Aceleración al convertir")
        t.setObjectName("PopoverTitle")
        pop.content.addWidget(t)
        self.encoder_combo = _combo(ENCODERS)
        pop.content.addWidget(self.encoder_combo)
        self.encoder_chip = Chip("Aceleración: GPU", pop)
        self.encoder_chip.cleared.connect(lambda: _select(self.encoder_combo, "auto"))
        flow.addWidget(self.encoder_chip)

        for combo in (self.encoder_combo, self.cookies_combo, self.subs_mode_combo, self.subs_lang_combo):
            combo.currentIndexChanged.connect(self._on_option_changed)

    # ---------- API pública ----------
    def set_default_dirs(self, dirs: dict):
        self._default_dirs = dict(dirs)
        if not self._folder_custom:
            self._set_folder(self._default_dirs.get(self.current_preset(), ""), custom=False)

    def current_preset(self) -> str:
        return self.preset_combo.currentData() or PRESET_MAX

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

    def set_cookies_browser(self, browser: str | None):
        _select(self.cookies_combo, browser)

    def save_options(self, settings):
        settings.setValue("encoder_mode", self.encoder_mode())
        settings.setValue("cookies_browser", self.cookies_combo.currentData() or "")
        settings.setValue("subs_mode", self.subs_mode_combo.currentData() or SUBS_NONE)
        settings.setValue("subs_langs", ",".join(self.subs_lang_combo.currentData() or ("es",)))

    def load_options(self, settings):
        _select(self.encoder_combo, str(settings.value("encoder_mode", "auto")))
        _select(self.cookies_combo, str(settings.value("cookies_browser", "")) or None)
        _select(self.subs_mode_combo, str(settings.value("subs_mode", SUBS_NONE)))
        langs = tuple(x for x in str(settings.value("subs_langs", "es")).split(",") if x)
        _select(self.subs_lang_combo, langs)
        self._refresh_chips()

    def set_url(self, url: str):
        self.url_edit.setText(url)
        self.url_edit.setFocus()

    def set_busy(self, busy: bool):
        """Con un trabajo en curso se puede seguir agregando a la cola."""
        self._is_busy = busy
        self.start_btn.setText("Añadir a la cola" if busy else "Descargar")

    def set_queue(self, jobs):
        """Reconstruye la lista (cuando entra o sale un trabajo)."""
        self.queue_list.clear()
        self._rows = {}
        for job in jobs:
            row = QueueRow(job)
            row.action.connect(self.request_job_action)
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            self.queue_list.addItem(item)
            self.queue_list.setItemWidget(item, row)
            self._rows[job.id] = row
        pending = sum(1 for j in jobs if j.status == "en cola")
        running = any(j.status == "descargando" for j in jobs)
        finished = any(j.status in ("listo", "error", "cancelado") for j in jobs)
        self.tabs.setTabText(0, f"Cola · {pending + running}" if pending or running else "Cola")
        self.queue_list.setVisible(bool(jobs))
        self.empty_label.setVisible(not jobs)
        self.cancel_all_btn.setVisible(running or pending > 0)
        self.clear_done_btn.setVisible(finished)
        parts = []
        if running:
            parts.append("1 activa")
        if pending:
            parts.append(f"{pending} en espera")
        self.queue_label.setText(" · ".join(parts))

    def update_job(self, job):
        row = self._rows.get(job.id)
        if row is not None:
            row.update_from(job)

    def set_tools_status(self, text: str):
        self.tools_label.setText(text)

    def append_log(self, text: str):
        self.log_box.append(text)

    # ---------- Interno ----------
    def _on_option_changed(self, *_):
        self._refresh_chips()
        self.options_changed.emit()

    def _refresh_chips(self, *_):
        s, e = self.start_edit.text().strip(), self.end_edit.text().strip()
        if s and e:
            self.trim_chip.set_value(f"✂ {s} – {e}")
        elif s:
            self.trim_chip.set_value(f"✂ desde {s}")
        elif e:
            self.trim_chip.set_value(f"✂ hasta {e}")
        else:
            self.trim_chip.set_value(None)

        mode = self.subs_mode_combo.currentData()
        self.subs_lang_combo.setEnabled(mode != SUBS_NONE)
        if mode == SUBS_NONE:
            self.subs_chip.set_value(None)
        else:
            how = ".srt" if mode == SUBS_SRT else "incrustados"
            self.subs_chip.set_value(f"CC {self.subs_lang_combo.currentText()} · {how}")

        b = self.cookies_combo.currentData()
        self.cookies_chip.set_value(f"Sesión: {browser_display_name(b)}" if b else None)
        self.encoder_chip.set_value("Aceleración: solo CPU" if self.encoder_mode() == "cpu" else None)

    def _clear_trim(self):
        self.start_edit.clear()
        self.end_edit.clear()

    def _on_preset_changed(self, *_):
        preset = self.current_preset()
        self.size_field.setVisible(preset == PRESET_TAMANO)
        if not self._folder_custom:
            self._set_folder(self._default_dirs.get(preset, ""), custom=False)
        self._reset_folder_act.setEnabled(self._folder_custom)

    def _set_folder(self, path: str, custom: bool):
        self._folder = path
        self._folder_custom = custom
        name = os.path.basename(os.path.normpath(path)) if path else "Elegir carpeta"
        self.folder_btn.setText(f"Carpeta:  {name}")
        self.folder_btn.setToolTip(path)
        self._reset_folder_act.setEnabled(custom)

    def _choose_folder(self):
        carpeta = QFileDialog.getExistingDirectory(
            self, "Elegir carpeta de salida", self._folder or os.path.expanduser("~")
        )
        if carpeta:
            self._set_folder(os.path.normpath(carpeta), custom=True)

    def _reset_folder(self):
        self._set_folder(self._default_dirs.get(self.current_preset(), ""), custom=False)

    def _open_folder(self):
        if self._folder and os.path.isdir(self._folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._folder))

    def _do_paste(self):
        clip = QGuiApplication.clipboard()
        text = (clip.text() if clip else "") or ""
        url = find_url_in_text(text) or text.strip()
        if url:
            self.url_edit.setText(url)
        self.url_edit.setFocus()

    def _on_start(self):
        url = self.url_edit.text().strip()
        preset = self.current_preset()
        if not url:
            self.url_edit.setPlaceholderText("Primero pega un enlace aquí")
            self.url_edit.setFocus()
            return
        if not is_http_url(url):
            self.append_log("⚠️ Esa URL no se ve válida: debe empezar con http:// o https://")
            self.tabs.setCurrentIndex(1)
            return
        if not self._folder:
            self._choose_folder()
            if not self._folder:
                return
        if preset == PRESET_TAMANO and self.target_size_mb() is None:
            self.size_combo.setFocus()
            self.append_log("⚠️ Escribe un peso máximo válido en MB (por ejemplo 25).")
            return
        self.request_start.emit(
            url, preset, self._folder, self.start_edit.text().strip(), self.end_edit.text().strip()
        )
        self.tabs.setCurrentIndex(0)

    # ---------- Arrastrar y soltar ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasText() or e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        text = md.text() if md.hasText() else ""
        if not text and md.hasUrls() and md.urls():
            text = md.urls()[0].toString()
        url = find_url_in_text(text) or text
        if url:
            self.url_edit.setText(url.strip())
