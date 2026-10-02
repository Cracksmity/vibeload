"""Vista simple: pegar el enlace, elegir Video o Solo audio, listo.

Cada elemento tiene un lugar fijo: la vista previa reserva su espacio antes de
cargar y el estado (progreso, listo, error) vive en una franja fija abajo, así
nada se mueve debajo del cursor.
"""
import os
import threading

from PySide6.QtCore import Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..config import PRESET_MAX, PRESET_MP3, SIMPLE_EXTRA_PRESETS, preset_label
from ..jobs import PHASE_CONVERTING, PHASE_DONE, PHASE_DOWNLOADING
from ..thumbnails import fetch_thumbnail_bytes
from ..urls import find_url_in_text, is_http_url, looks_like_supported_url
from ..utils import format_duration
from .widgets import ElidedLabel, repolish

THUMB_W, THUMB_H = 128, 72


def image_from_bytes(data: bytes) -> QImage | None:
    """Decodifica y escala con QImage: se puede usar fuera del hilo de la GUI
    (QPixmap no; usarlo en un hilo secundario puede cerrar la app)."""
    img = QImage()
    if not data or not img.loadFromData(data) or img.isNull():
        return None
    return img.scaled(
        THUMB_W, THUMB_H, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
    )


def short_folder(path: str, parts: int = 2) -> str:
    """'C:\\Users\\Ana\\Videos\\VibeLoader\\HD' -> 'VibeLoader › HD'."""
    bits = [b for b in os.path.normpath(path or "").split(os.sep) if b and not b.endswith(":")]
    return " › ".join(bits[-parts:]) if bits else path


def format_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return ""
    if seconds < 60:
        return f"quedan {max(5, int(round(seconds / 5.0)) * 5)} s"
    minutes = int(round(seconds / 60.0))
    return "queda 1 min" if minutes <= 1 else f"quedan {minutes} min"


class ChoiceButton(QPushButton):
    """Botón grande con ícono, título y una línea de detalle."""

    def __init__(self, icon: str, title: str, sub: str, primary: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("choicePrimary" if primary else "choiceAlt")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"{title}, {sub}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(14)
        ic = QLabel(icon)
        ic.setObjectName("ChoiceIcon")
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addStretch()
        t = QLabel(title)
        t.setObjectName("ChoiceTitle")
        s = QLabel(sub)
        s.setObjectName("ChoiceSub")
        col.addWidget(t)
        col.addWidget(s)
        col.addStretch()
        lay.addLayout(col, 1)
        for w in (ic, t, s):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class SimpleView(QWidget):
    request_fetch_metadata = Signal(str, int)
    request_open_folders = Signal()
    request_start = Signal(str, str)  # url, preset
    request_cancel = Signal()
    _thumbnail_loaded = Signal(QImage, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SimpleView")
        self.setAcceptDrops(True)
        self.last_preset = PRESET_MAX  # Enter repite la última elección
        self._token = 0
        self._last_url = ""
        self._autopasted = ""
        self._last_result_path = None
        self._is_busy = False
        self._queue_count = 0
        self._eta = None
        self._fetch_timer = QTimer(self)
        self._fetch_timer.setSingleShot(True)
        self._fetch_timer.setInterval(450)
        self._fetch_timer.timeout.connect(self._trigger_fetch)
        self._idle_reset = QTimer(self)
        self._idle_reset.setSingleShot(True)
        self._idle_reset.timeout.connect(self._restore_idle_text)
        self._folder_text = ""
        self._thumbnail_loaded.connect(self._on_thumbnail_loaded)
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QVBoxLayout()
        body.setContentsMargins(24, 18, 24, 12)
        body.setSpacing(12)
        root.addLayout(body, 1)

        # Enlace
        url_row = QHBoxLayout()
        url_row.setSpacing(10)
        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("bigUrl")
        self.url_edit.setPlaceholderText("Pega el enlace del video")
        self.url_edit.setAccessibleName("Enlace del video")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.textChanged.connect(self._on_url_changed)
        self.url_edit.returnPressed.connect(lambda: self._start(self.last_preset))
        url_row.addWidget(self.url_edit, 1)
        self.paste_btn = QPushButton("Pegar")
        self.paste_btn.setObjectName("secondary")
        self.paste_btn.setMinimumHeight(52)
        self.paste_btn.setToolTip("Pega el enlace que copiaste (Ctrl+V)")
        self.paste_btn.clicked.connect(self._do_paste)
        url_row.addWidget(self.paste_btn)
        body.addLayout(url_row)

        # Línea de ayuda (altura fija: avisos de auto-pegado o validación)
        self.hint = QLabel("")
        self.hint.setObjectName("Hint")
        self.hint.setFixedHeight(20)
        self.hint.setTextFormat(Qt.TextFormat.RichText)
        self.hint.linkActivated.connect(self._on_hint_link)
        body.addWidget(self.hint)

        # Vista previa (espacio reservado)
        self.preview = QFrame()
        self.preview.setObjectName("Preview")
        self.preview.setFixedHeight(THUMB_H + 22)
        self.preview_pages = QStackedLayout(self.preview)
        self.preview_empty = QLabel("La vista previa del video aparece aquí")
        self.preview_empty.setObjectName("Dim")
        self.preview_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_pages.addWidget(self.preview_empty)
        loaded = QWidget()
        pl = QHBoxLayout(loaded)
        pl.setContentsMargins(10, 10, 14, 10)
        pl.setSpacing(14)
        self.thumb = QLabel()
        self.thumb.setObjectName("Thumb")
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl.addWidget(self.thumb)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addStretch()
        self.preview_title = ElidedLabel("")
        self.preview_title.setObjectName("PreviewTitle")
        self.preview_meta = QLabel("")
        self.preview_meta.setObjectName("Meta")
        col.addWidget(self.preview_title)
        col.addWidget(self.preview_meta)
        col.addStretch()
        pl.addLayout(col, 1)
        self.preview_pages.addWidget(loaded)
        body.addWidget(self.preview)

        # Elecciones
        choices = QHBoxLayout()
        choices.setSpacing(12)
        self.btn_video = ChoiceButton("▶", "Video", "Mejor calidad", primary=True)
        self.btn_video.clicked.connect(lambda: self._start(PRESET_MAX))
        self.btn_audio = ChoiceButton("♪", "Solo audio", "MP3", primary=False)
        self.btn_audio.clicked.connect(lambda: self._start(PRESET_MP3))
        choices.addWidget(self.btn_video)
        choices.addWidget(self.btn_audio)
        body.addLayout(choices)

        more_row = QHBoxLayout()
        self.more_btn = QToolButton()
        self.more_btn.setObjectName("MoreFormats")
        self.more_btn.setText("Más formatos ▾")
        self.more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.more_btn)
        for preset in SIMPLE_EXTRA_PRESETS:
            act = menu.addAction(preset_label(preset))
            act.triggered.connect(lambda _=False, p=preset: self._start(p))
        self.more_btn.setMenu(menu)
        more_row.addWidget(self.more_btn)
        more_row.addStretch()
        body.addLayout(more_row)
        body.addStretch()

        # Franja de estado
        self.strip = QFrame()
        self.strip.setObjectName("StatusStrip")
        self.strip.setFixedHeight(76)
        sl = QVBoxLayout(self.strip)
        sl.setContentsMargins(24, 0, 20, 0)
        self.pages = QStackedWidget()
        sl.addWidget(self.pages)
        root.addWidget(self.strip)

        # Reposo
        idle = QWidget()
        il = QHBoxLayout(idle)
        il.setContentsMargins(0, 0, 0, 0)
        self.idle_text = QLabel("")
        self.idle_text.setObjectName("Dim")
        self.idle_text.setTextFormat(Qt.TextFormat.RichText)
        il.addWidget(self.idle_text, 1)
        self.change_folder_btn = QPushButton("Cambiar")
        self.change_folder_btn.setObjectName("ghost")
        self.change_folder_btn.setToolTip("Elegir dónde se guarda cada formato")
        self.change_folder_btn.clicked.connect(self.request_open_folders)
        il.addWidget(self.change_folder_btn)
        self.pages.addWidget(idle)

        # Descargando
        busy = QWidget()
        bl = QHBoxLayout(busy)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(16)
        bcol = QVBoxLayout()
        bcol.setSpacing(8)
        bcol.addStretch()
        brow = QHBoxLayout()
        self.busy_title = QLabel("Preparando…")
        self.busy_title.setObjectName("StatusTitle")
        self.busy_eta = QLabel("")
        self.busy_eta.setObjectName("Dim")
        brow.addWidget(self.busy_title)
        brow.addStretch()
        brow.addWidget(self.busy_eta)
        bcol.addLayout(brow)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        bcol.addWidget(self.progress)
        bcol.addStretch()
        bl.addLayout(bcol, 1)
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setObjectName("secondary")
        self.cancel_btn.clicked.connect(self.request_cancel)
        bl.addWidget(self.cancel_btn)
        self.pages.addWidget(busy)

        # Listo
        done = QWidget()
        dl = QHBoxLayout(done)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(12)
        dot = QLabel("✓")
        dot.setObjectName("StatusDot")
        dot.setProperty("kind", "ok")
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(dot)
        dcol = QVBoxLayout()
        dcol.setSpacing(0)
        dcol.addStretch()
        self.done_title = ElidedLabel("")
        self.done_title.setObjectName("StatusTitle")
        self.done_meta = ElidedLabel("")
        self.done_meta.setObjectName("Meta")
        dcol.addWidget(self.done_title)
        dcol.addWidget(self.done_meta)
        dcol.addStretch()
        dl.addLayout(dcol, 1)
        self.open_file_btn = QPushButton("Abrir")
        self.open_file_btn.clicked.connect(self._open_result_file)
        self.open_folder_btn = QPushButton("Ver en carpeta")
        self.open_folder_btn.setObjectName("secondary")
        self.open_folder_btn.clicked.connect(self._open_result_folder)
        dl.addWidget(self.open_file_btn)
        dl.addWidget(self.open_folder_btn)
        self.pages.addWidget(done)

        # Error
        err = QWidget()
        el = QHBoxLayout(err)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(12)
        edot = QLabel("!")
        edot.setObjectName("StatusDot")
        edot.setProperty("kind", "error")
        edot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addWidget(edot)
        ecol = QVBoxLayout()
        ecol.setSpacing(0)
        ecol.addStretch()
        self.error_title = QLabel("")
        self.error_title.setObjectName("StatusTitle")
        self.error_title.setWordWrap(True)
        self.error_meta = QLabel("")
        self.error_meta.setObjectName("Meta")
        ecol.addWidget(self.error_title)
        ecol.addWidget(self.error_meta)
        ecol.addStretch()
        el.addLayout(ecol, 1)
        self.error_btn = QPushButton("")
        self.error_btn.clicked.connect(self._on_error_button)
        el.addWidget(self.error_btn)
        close = QToolButton()
        close.setObjectName("RowAction")
        close.setText("✕")
        close.setToolTip("Cerrar aviso")
        close.clicked.connect(self._show_idle)
        el.addWidget(close)
        self.pages.addWidget(err)
        self._error_action = None

        QShortcut(QKeySequence.StandardKey.Paste, self, self._do_paste)
        self._set_preview_state("empty")

    # ---------- API pública ----------
    def set_busy(self, busy: bool):
        """Durante una descarga los botones siguen activos: lo nuevo va a la cola."""
        self._is_busy = busy
        self.change_folder_btn.setEnabled(not busy)
        if busy:
            self._eta = None
            self.progress.setValue(0)
            self.busy_title.setText("Preparando…")
            self.busy_eta.setText("")
            self.pages.setCurrentIndex(1)
        elif self.pages.currentIndex() == 1:
            self._show_idle()

    def set_progress(self, info):
        if not self._is_busy:
            return
        self.progress.setValue(info.pct)
        if info.phase == PHASE_CONVERTING:
            title = "Preparando tu archivo…"
        elif info.phase == PHASE_DONE:
            title = "Terminando…"
        elif info.phase == PHASE_DOWNLOADING and (info.speed or info.pct > 2):
            title = "Descargando…"
        else:
            title = "Preparando…"
        if self._queue_count:
            title += f"  ·  {self._queue_count} más en cola"
        self.busy_title.setText(title)
        if info.phase == PHASE_DOWNLOADING and info.eta is not None:
            # Media móvil: el tiempo restante no salta de «4 min» a «20 s».
            self._eta = info.eta if self._eta is None else 0.3 * info.eta + 0.7 * self._eta
            self.busy_eta.setText(format_eta(self._eta))
        elif info.phase != PHASE_DOWNLOADING:
            self.busy_eta.setText("")

    def set_queue_count(self, n: int):
        self._queue_count = n

    def show_success(self, file_path: str, note: str = ""):
        self._last_result_path = file_path
        name = os.path.basename(file_path) if file_path else ""
        self.done_title.setText(f"Listo · {name}" if name else "Listo")
        folder = f"En {short_folder(os.path.dirname(file_path), 3)}" if file_path else ""
        self.done_meta.setText(" · ".join(x for x in (note, folder) if x))
        self.open_file_btn.setVisible(bool(file_path))
        self.open_folder_btn.setVisible(bool(file_path))
        self.pages.setCurrentIndex(2)

    def show_error(self, text: str, button_text: str | None = None, action=None, note: str = ""):
        self.error_title.setText(text)
        self.error_meta.setText(note)
        self.error_meta.setVisible(bool(note))
        self._error_action = action
        self.error_btn.setVisible(bool(button_text and action))
        if button_text:
            self.error_btn.setText(button_text)
        self.pages.setCurrentIndex(3)

    def clear_status(self):
        """Vuelve la franja inferior al estado de reposo (o al progreso si hay descarga)."""
        self._show_idle()

    def show_cancelled(self):
        self._show_idle()
        self.idle_text.setText("Cancelado.")
        self._idle_reset.start(4000)

    def update_folder_hint(self, dirs: dict):
        video = short_folder(dirs.get(PRESET_MAX, ""), 1)
        music = short_folder(dirs.get(PRESET_MP3, ""), 1)
        self._folder_text = f"Videos en <b>{video}</b> · Música en <b>{music}</b>"
        self.idle_text.setToolTip(
            f"Video: {dirs.get(PRESET_MAX, '')}\nSolo audio: {dirs.get(PRESET_MP3, '')}"
        )
        self._restore_idle_text()

    def set_url(self, url: str):
        self.url_edit.setText(url)
        self.url_edit.setFocus()

    def maybe_autopaste_clipboard(self):
        if self._is_busy or self.url_edit.text().strip():
            return
        clip = QGuiApplication.clipboard()
        if clip is None:
            return
        url = find_url_in_text(clip.text() or "")
        if url and looks_like_supported_url(url) and url != self._autopasted:
            self._autopasted = url
            self.url_edit.setText(url)
            self._set_hint('Usamos el enlace que copiaste · <a href="clear">Quitar</a>')

    @Slot(dict, int)
    def on_metadata(self, data, token):
        if token != self._token or data.get("url") != self._last_url:
            return
        self.preview_title.setText(data.get("title") or "(sin título)")
        meta = []
        if data.get("channel"):
            meta.append(data["channel"])
        if data.get("is_playlist"):
            n = data.get("playlist_count") or 0
            meta.append(f"Lista de {n} videos · podrás elegir cuáles" if n else "Lista de reproducción")
        else:
            d = format_duration(data.get("duration"))
            if d:
                meta.append(d)
        self.preview_meta.setText(" · ".join(meta))
        urls = data.get("thumbnail_urls") or []
        if not urls and data.get("thumbnail"):
            urls = [data["thumbnail"]]
        if urls:
            self._load_thumbnail_async(urls, token)

    @Slot(str, int)
    def on_metadata_failed(self, _msg, token):
        if token != self._token:
            return
        self.preview_title.setText("No pudimos ver la vista previa")
        self.preview_meta.setText("Igual puedes intentar descargarlo.")

    # ---------- Interno ----------
    def _set_preview_state(self, state: str):
        self.preview_pages.setCurrentIndex(0 if state == "empty" else 1)
        self.preview.setProperty("state", state)
        repolish(self.preview)

    def _set_hint(self, html: str, error: bool = False):
        self.hint.setText(html)
        self.hint.setProperty("kind", "error" if error else "")
        repolish(self.hint)

    def _on_hint_link(self, href: str):
        if href == "clear":
            self.url_edit.clear()
            self.url_edit.setFocus()

    def _show_idle(self):
        self.pages.setCurrentIndex(1 if self._is_busy else 0)

    def _restore_idle_text(self):
        self.idle_text.setText(self._folder_text)

    def _on_url_changed(self, text: str):
        url = text.strip()
        if url != self._autopasted:
            self._set_hint("")
        if self.pages.currentIndex() in (2, 3):
            self._show_idle()
        self.thumb.clear()
        if is_http_url(url):
            self._last_url = url
            self.preview_title.setText("Buscando el video…")
            self.preview_meta.setText("")
            self._set_preview_state("loading")
            self._fetch_timer.start()
        else:
            self._fetch_timer.stop()
            self._last_url = ""
            self._token += 1  # descarta respuestas pendientes
            self._set_preview_state("empty")

    def _trigger_fetch(self):
        if not self._last_url:
            return
        self._token += 1
        self.request_fetch_metadata.emit(self._last_url, self._token)

    def _load_thumbnail_async(self, urls, token: int):
        """Descarga la miniatura en otro hilo; el pixmap se aplica en la GUI vía señal."""
        urls_copy = list(urls)[:6]

        def _fetch():
            for url in urls_copy:
                if token != self._token:
                    return
                try:
                    img = image_from_bytes(fetch_thumbnail_bytes(url))
                except Exception:
                    continue
                if img is not None:
                    self._thumbnail_loaded.emit(img, token)
                    return

        threading.Thread(target=_fetch, daemon=True).start()

    @Slot(QImage, int)
    def _on_thumbnail_loaded(self, img: QImage, token: int):
        if token != self._token or img.isNull():
            return
        pix = QPixmap.fromImage(img)
        x = max(0, (pix.width() - THUMB_W) // 2)
        y = max(0, (pix.height() - THUMB_H) // 2)
        self.thumb.setPixmap(pix.copy(x, y, THUMB_W, THUMB_H))

    def _do_paste(self):
        clip = QGuiApplication.clipboard()
        text = (clip.text() if clip else "") or ""
        url = find_url_in_text(text) or text.strip()
        if url:
            self.url_edit.setText(url)
        self.url_edit.setFocus()

    def _start(self, preset: str):
        url = self.url_edit.text().strip()
        if not url:
            self._set_hint("Primero pega el enlace del video.", error=True)
            self.url_edit.setFocus()
            return
        if not is_http_url(url):
            self._set_hint("Eso no parece un enlace. Cópialo desde el botón Compartir del video.", error=True)
            self.url_edit.setFocus()
            return
        self.last_preset = preset
        self._set_hint("")
        self.request_start.emit(url, preset)

    def _on_error_button(self):
        if self._error_action:
            self._error_action()

    def _open_result_folder(self):
        if not self._last_result_path:
            return
        folder = os.path.dirname(self._last_result_path)
        if folder and os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _open_result_file(self):
        if self._last_result_path and os.path.exists(self._last_result_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_result_path))

    # ---------- Arrastrar y soltar ----------
    def _set_drop_highlight(self, on: bool):
        self.url_edit.setProperty("drop", "true" if on else "false")
        repolish(self.url_edit)

    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasText() or md.hasUrls():
            e.acceptProposedAction()
            self._set_drop_highlight(True)

    def dragLeaveEvent(self, e):
        self._set_drop_highlight(False)
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self._set_drop_highlight(False)
        md = e.mimeData()
        text = md.text() if md.hasText() else ""
        if not text and md.hasUrls() and md.urls():
            text = md.urls()[0].toString()
        url = find_url_in_text(text) or text
        if url:
            self.url_edit.setText(url.strip())
