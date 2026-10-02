"""Vista simple: pegar enlace y elegir un botón."""
import html
import os
import threading

from PySide6.QtCore import Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..config import PRESET_CAR, PRESET_DIRECTO, PRESET_MAX, PRESET_MP3
from ..errors import friendly
from ..thumbnails import fetch_thumbnail_bytes, image_from_bytes
from ..urls import find_url_in_text, is_http_url, looks_like_supported_url
from ..utils import format_duration


class SimpleView(QWidget):
    """Pegar enlace -> elegir Música / Video / Auto / Cursos -> descargar."""

    request_fetch_metadata = Signal(str, int)
    request_open_advanced = Signal()
    request_open_folders = Signal()
    request_open_history = Signal()
    request_toggle_theme = Signal()
    request_start = Signal(str, str)
    request_cancel = Signal()
    _thumbnail_loaded = Signal(QImage, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._token = 0
        self._last_url = ""
        self._last_result_path = None
        self._is_busy = False
        self._fetch_timer = QTimer(self)
        self._fetch_timer.setSingleShot(True)
        self._fetch_timer.setInterval(450)
        self._fetch_timer.timeout.connect(self._trigger_fetch)
        self._thumbnail_loaded.connect(self._on_thumbnail_loaded)
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)

        # Top bar
        top = QHBoxLayout()
        title = QLabel("VibeLoader")
        title.setObjectName("TitleLabel")
        top.addWidget(title)
        top.addStretch()
        self.theme_btn = QToolButton()
        self.theme_btn.setText("Tema")
        self.theme_btn.setToolTip("Cambiar entre claro y oscuro")
        self.theme_btn.clicked.connect(self.request_toggle_theme)
        top.addWidget(self.theme_btn)
        self.history_btn = QToolButton()
        self.history_btn.setText("Historial")
        self.history_btn.setToolTip("Tus últimas descargas")
        self.history_btn.clicked.connect(self.request_open_history)
        top.addWidget(self.history_btn)
        self.advanced_btn = QToolButton()
        self.advanced_btn.setText("Modo avanzado")
        self.advanced_btn.clicked.connect(self.request_open_advanced)
        top.addWidget(self.advanced_btn)
        layout.addLayout(top)

        sub = QLabel("Pega el enlace y elige cómo descargar.")
        sub.setObjectName("SubtitleLabel")
        layout.addWidget(sub)

        # Aviso (falta ffmpeg, yt-dlp actualizado…)
        self.notice_card = QFrame()
        self.notice_card.setObjectName("card_notice")
        self.notice_card.setVisible(False)
        nl = QHBoxLayout(self.notice_card)
        nl.setContentsMargins(12, 8, 12, 8)
        self.notice_text = QLabel("")
        self.notice_text.setWordWrap(True)
        nl.addWidget(self.notice_text, 1)
        self.notice_btn = QPushButton("")
        self.notice_btn.clicked.connect(self._on_notice_clicked)
        nl.addWidget(self.notice_btn)
        self._notice_action = None
        layout.addWidget(self.notice_card)

        # URL row
        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("bigUrl")
        self.url_edit.setPlaceholderText("Pega aquí el enlace (YouTube, TikTok, Facebook, Instagram…)")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.textChanged.connect(self._on_url_changed)
        url_row.addWidget(self.url_edit, 1)

        self.paste_btn = QPushButton("Pegar")
        self.paste_btn.setObjectName("secondary")
        self.paste_btn.clicked.connect(self._do_paste)
        url_row.addWidget(self.paste_btn)

        self.recents_btn = QToolButton()
        self.recents_btn.setText("Recientes")
        self.recents_btn.setToolTip("Últimos enlaces usados")
        self.recents_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._recents_menu = QMenu(self)
        self.recents_btn.setMenu(self._recents_menu)
        self.recents_btn.setEnabled(False)
        url_row.addWidget(self.recents_btn)

        layout.addLayout(url_row)

        # Preview
        self.preview = QFrame()
        self.preview.setObjectName("preview")
        self.preview.setVisible(False)
        prev_layout = QHBoxLayout(self.preview)
        prev_layout.setContentsMargins(10, 10, 10, 10)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(160, 90)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet(
            "background: transparent; border: 1px solid rgba(127,127,127,0.25); border-radius: 6px;"
        )
        prev_layout.addWidget(self.thumb_label)

        text_col = QVBoxLayout()
        self.preview_title = QLabel("Cargando…")
        self.preview_title.setObjectName("PreviewTitle")
        self.preview_title.setWordWrap(True)
        self.preview_meta = QLabel("")
        self.preview_meta.setObjectName("PreviewMeta")
        text_col.addWidget(self.preview_title)
        text_col.addWidget(self.preview_meta)
        text_col.addStretch()
        prev_layout.addLayout(text_col, 1)
        layout.addWidget(self.preview)

        # Action buttons (grid 2×2)
        btn_grid = QVBoxLayout()
        btn_grid.setSpacing(12)

        row_top = QHBoxLayout()
        row_top.setSpacing(12)
        self.btn_music = QPushButton("Descargar Música\n(MP3)")
        self.btn_music.setObjectName("big_music")
        self.btn_music.clicked.connect(lambda: self._start(PRESET_MP3))

        self.btn_video = QPushButton("Descargar Video\n(hasta 1080p)")
        self.btn_video.setObjectName("big_video")
        self.btn_video.clicked.connect(lambda: self._start(PRESET_MAX))

        self.btn_car = QPushButton("Modo Auto\n(autoestéreo)")
        self.btn_car.setObjectName("big_car")
        self.btn_car.setToolTip(
            "Descarga y reconvierte a un MP4 en 720p compatible con autoestéreos"
        )
        self.btn_car.clicked.connect(lambda: self._start(PRESET_CAR))

        self.btn_directo = QPushButton("Descarga Directa\n(720p sin recodificar)")
        self.btn_directo.setObjectName("big_directo")
        self.btn_directo.setToolTip(
            "Descarga directa desde YouTube en 720p SDR, evita el sobrecalentamiento del CPU"
        )
        self.btn_directo.clicked.connect(lambda: self._start(PRESET_DIRECTO))

        for b in (self.btn_music, self.btn_video, self.btn_directo, self.btn_car):
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        
        row_mid = QHBoxLayout()
        row_mid.setSpacing(12)
        
        row_top.addWidget(self.btn_music)
        row_top.addWidget(self.btn_video)
        row_mid.addWidget(self.btn_directo)
        row_mid.addWidget(self.btn_car)
        
        btn_grid.addLayout(row_top)
        btn_grid.addLayout(row_mid)
        layout.addLayout(btn_grid)

        # Folder hint
        folder_row = QHBoxLayout()
        self.folder_hint = QLabel("")
        self.folder_hint.setObjectName("FolderHint")
        folder_row.addWidget(self.folder_hint, 1)
        self.change_folder_btn = QPushButton("Cambiar carpetas…")
        self.change_folder_btn.setObjectName("secondary")
        self.change_folder_btn.clicked.connect(self.request_open_folders)
        folder_row.addWidget(self.change_folder_btn)
        layout.addLayout(folder_row)

        # Progress + cancel
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Esperando…")
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setObjectName("secondary")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.request_cancel)
        cancel_row = QHBoxLayout()
        self.queue_label = QLabel("")
        self.queue_label.setObjectName("FolderHint")
        cancel_row.addWidget(self.queue_label)
        cancel_row.addStretch()
        cancel_row.addWidget(self.cancel_btn)
        layout.addLayout(cancel_row)

        # Result card
        self.result_card = QFrame()
        self.result_card.setObjectName("card_success")
        self.result_card.setVisible(False)
        rl = QVBoxLayout(self.result_card)
        rl.setContentsMargins(12, 10, 12, 10)
        self.result_text = QLabel("")
        self.result_text.setWordWrap(True)
        rl.addWidget(self.result_text)
        rb = QHBoxLayout()
        self.open_folder_btn = QPushButton("Abrir carpeta")
        self.open_folder_btn.clicked.connect(self._open_result_folder)
        self.open_file_btn = QPushButton("Abrir archivo")
        self.open_file_btn.setObjectName("secondary")
        self.open_file_btn.clicked.connect(self._open_result_file)
        self.again_btn = QPushButton("Otra descarga")
        self.again_btn.setObjectName("secondary")
        self.again_btn.clicked.connect(self._reset_for_new_download)
        rb.addWidget(self.open_folder_btn)
        rb.addWidget(self.open_file_btn)
        rb.addWidget(self.again_btn)
        rb.addStretch()
        rl.addLayout(rb)
        layout.addWidget(self.result_card)

        # Error card
        self.error_card = QFrame()
        self.error_card.setObjectName("card_error")
        self.error_card.setVisible(False)
        el = QVBoxLayout(self.error_card)
        el.setContentsMargins(12, 10, 12, 10)
        self.error_text = QLabel("")
        self.error_text.setWordWrap(True)
        el.addWidget(self.error_text)
        eb = QHBoxLayout()
        self.retry_btn = QPushButton("Reintentar")
        self.retry_btn.setObjectName("secondary")
        self.retry_btn.clicked.connect(self._on_retry)
        self.dismiss_btn = QPushButton("Cerrar aviso")
        self.dismiss_btn.setObjectName("secondary")
        self.dismiss_btn.clicked.connect(lambda: self.error_card.setVisible(False))
        eb.addWidget(self.retry_btn)
        eb.addWidget(self.dismiss_btn)
        eb.addStretch()
        el.addLayout(eb)
        layout.addWidget(self.error_card)

        layout.addStretch()

    # ---------- Public API ----------
    def set_busy(self, busy: bool):
        """Durante una descarga los botones siguen activos: lo nuevo va a la cola."""
        self._is_busy = busy
        self.change_folder_btn.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.cancel_btn.setVisible(busy)
        if not busy:
            self.queue_label.setText("")
        if busy:
            self.result_card.setVisible(False)
            self.error_card.setVisible(False)
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setFormat("Iniciando…")

    def set_progress(self, pct: int, detail: str):
        if not self._is_busy:
            return
        self.progress.setRange(0, 100)
        self.progress.setValue(pct)
        self.progress.setFormat(detail or f"{pct}%")

    def set_queue_count(self, n: int):
        self.queue_label.setText(f"En cola: {n}" if n else "")

    def show_success(self, file_path: str, note: str = ""):
        self._last_result_path = file_path
        extra = f"<br><span style='color:#888;'>{html.escape(note)}</span>" if note else ""
        self.result_text.setTextFormat(Qt.TextFormat.RichText)
        if file_path:
            self.result_text.setText(
                f"Listo. Tu archivo:<br><b>{html.escape(os.path.basename(file_path))}</b><br>"
                f"<span style='color:#888;'>Carpeta: {html.escape(os.path.dirname(file_path))}</span>"
                + extra
            )
        else:
            self.result_text.setText("Listo." + extra)
        self.result_card.setVisible(True)
        self.error_card.setVisible(False)

    def show_error(self, msg: str):
        self.error_text.setText(f"⚠ {friendly(msg)}")
        self.error_card.setVisible(True)
        self.result_card.setVisible(False)

    def show_notice(self, text: str, button_text: str | None = None, action=None):
        """Aviso persistente arriba de la vista (con botón opcional)."""
        self.notice_text.setText(text)
        self._notice_action = action
        self.notice_btn.setVisible(bool(button_text and action))
        if button_text:
            self.notice_btn.setText(button_text)
        self.notice_card.setVisible(True)

    def hide_notice(self):
        self.notice_card.setVisible(False)
        self._notice_action = None

    def _on_notice_clicked(self):
        if self._notice_action:
            self._notice_action()

    def show_cancelled(self):
        self.error_text.setText("Descarga cancelada.")
        self.error_card.setVisible(True)
        self.result_card.setVisible(False)

    def update_folder_hint(self, dirs: dict):
        parts = []
        if dirs.get(PRESET_MP3):
            parts.append(f"Música → {os.path.basename(dirs[PRESET_MP3])}")
        if dirs.get(PRESET_MAX):
            parts.append(f"Video → {os.path.basename(dirs[PRESET_MAX])}")
        if dirs.get(PRESET_CAR):
            parts.append(f"Auto → {os.path.basename(dirs[PRESET_CAR])}")
        if dirs.get(PRESET_DIRECTO):
            parts.append(f"Directo → {os.path.basename(dirs[PRESET_DIRECTO])}")
        self.folder_hint.setText("Se guardará en: " + " · ".join(parts) if parts else "")

    def set_recents(self, urls):
        self._recents_menu.clear()
        if not urls:
            self.recents_btn.setEnabled(False)
            return
        self.recents_btn.setEnabled(True)
        for u in urls:
            label = u if len(u) <= 70 else u[:67] + "…"
            act = QAction(label, self._recents_menu)
            act.triggered.connect(lambda _=False, x=u: self._use_recent(x))
            self._recents_menu.addAction(act)

    def maybe_autopaste_clipboard(self):
        if self._is_busy:
            return
        if self.url_edit.text().strip():
            return
        clip = QGuiApplication.clipboard()
        if clip is None:
            return
        text = clip.text() or ""
        url = find_url_in_text(text)
        if url and looks_like_supported_url(url):
            self.url_edit.setText(url)

    @Slot(dict, int)
    def on_metadata(self, data, token):
        if token != self._token:
            return
        if data.get("url") != self._last_url:
            return
        self.preview_title.setText(data.get("title") or "(sin título)")
        meta = []
        if data.get("channel"):
            meta.append(data["channel"])
        if data.get("is_playlist"):
            n = data.get("playlist_count") or 0
            meta.append(f"Lista de reproducción · {n} videos" if n else "Lista de reproducción")
            meta.append("elige un modo para escoger los videos")
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

    @Slot(QImage, int)
    def _on_thumbnail_loaded(self, img: QImage, token: int):
        if token != self._token or img.isNull():
            return
        self.thumb_label.setPixmap(QPixmap.fromImage(img))

    @Slot(str, int)
    def on_metadata_failed(self, msg, token):
        if token != self._token:
            return
        self.preview.setVisible(False)

    # ---------- Internal ----------
    def _on_url_changed(self, text: str):
        self.preview.setVisible(False)
        self.error_card.setVisible(False)
        self.result_card.setVisible(False)
        url = text.strip()
        if is_http_url(url):
            self._last_url = url
            self._fetch_timer.start()
        else:
            self._fetch_timer.stop()

    def _trigger_fetch(self):
        if not self._last_url:
            return
        self._token += 1
        self.thumb_label.clear()
        self.preview_title.setText("Cargando información…")
        self.preview_meta.setText("")
        self.preview.setVisible(True)
        self.request_fetch_metadata.emit(self._last_url, self._token)

    def _load_thumbnail_async(self, urls, token: int):
        """Descarga miniatura en hilo aparte; aplica pixmap en hilo GUI vía señal."""
        if isinstance(urls, str):
            urls = [urls] if urls else []
        if not urls:
            return
        my_token = token
        urls_copy = list(urls)

        def _fetch():
            for url in urls_copy[:6]:
                if my_token != self._token:
                    return
                try:
                    img = image_from_bytes(fetch_thumbnail_bytes(url))
                except Exception:
                    continue
                if img is not None:
                    self._thumbnail_loaded.emit(img, my_token)
                    return

        threading.Thread(target=_fetch, daemon=True).start()

    def _do_paste(self):
        clip = QGuiApplication.clipboard()
        if clip is None:
            return
        text = clip.text() or ""
        url = find_url_in_text(text) or text.strip()
        if url:
            self.url_edit.setText(url)
            self.url_edit.setFocus()

    def _use_recent(self, url: str):
        self.url_edit.setText(url)

    def _start(self, preset: str):
        url = self.url_edit.text().strip()
        if not url:
            self.show_error("Pega un enlace antes de descargar.")
            return
        if not is_http_url(url):
            self.show_error(
                "Ese enlace no se ve válido. Copia el enlace completo, que empiece con https://"
            )
            return
        self.error_card.setVisible(False)
        self.result_card.setVisible(False)
        self.request_start.emit(url, preset)

    def _reset_for_new_download(self):
        self.url_edit.clear()
        self.preview.setVisible(False)
        self.result_card.setVisible(False)
        self.error_card.setVisible(False)
        self.progress.setVisible(False)
        self.url_edit.setFocus()

    def _on_retry(self):
        self.error_card.setVisible(False)
        self.url_edit.setFocus()

    def _open_result_folder(self):
        if not self._last_result_path:
            return
        folder = os.path.dirname(self._last_result_path)
        if folder and os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _open_result_file(self):
        if self._last_result_path and os.path.exists(self._last_result_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_result_path))

    # ---------- Drag & drop ----------
    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasText() or md.hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        text = ""
        if md.hasText():
            text = md.text()
        elif md.hasUrls():
            urls = md.urls()
            if urls:
                text = urls[0].toString()
        url = find_url_in_text(text) or text
        if url:
            self.url_edit.setText(url.strip())
