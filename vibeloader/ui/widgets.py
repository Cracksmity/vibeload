"""Componentes compartidos: cabecera, control segmentado, aviso, chip con popover y FlowLayout."""
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .brand import BrandMark


def repolish(w: QWidget):
    """Reaplica la hoja de estilos tras cambiar una propiedad usada en selectores."""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


class Segmented(QFrame):
    """Dos o más opciones exclusivas que muestran en cuál estás (no adónde vas)."""

    changed = Signal(int)

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        self.setObjectName("Segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for i, text in enumerate(labels):
            b = QPushButton(text)
            b.setObjectName("SegButton")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # el foco con clic confundiría el estado
            self._group.addButton(b, i)
            lay.addWidget(b)
        self._group.idClicked.connect(self.changed)

    def set_index(self, i: int):
        b = self._group.button(i)
        if b is not None:
            b.setChecked(True)


class Header(QFrame):
    """Símbolo + wordmark a la izquierda; modo, historial y menú ⋯ a la derecha."""

    mode_changed = Signal(int)  # 0 = Simple, 1 = Avanzado
    history_clicked = Signal()

    def __init__(self, menu, parent=None):
        super().__init__(parent)
        self.setObjectName("Header")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 10, 16, 10)
        lay.setSpacing(8)
        self.mark = BrandMark(22)
        lay.addWidget(self.mark)
        word = QLabel("vibeloader")
        word.setObjectName("Wordmark")
        lay.addWidget(word)
        lay.addStretch()

        self.modes = Segmented(["Simple", "Avanzado"])
        self.modes.setToolTip("Simple: pegar y descargar. Avanzado: formatos, recortes y cola.")
        self.modes.changed.connect(self.mode_changed)
        lay.addWidget(self.modes)

        self.history_btn = QToolButton()
        self.history_btn.setObjectName("HeaderButton")
        self.history_btn.setText("Historial")
        self.history_btn.setToolTip("Tus últimas descargas")
        self.history_btn.clicked.connect(self.history_clicked)
        lay.addWidget(self.history_btn)

        self.more_btn = QToolButton()
        self.more_btn.setObjectName("MoreButton")
        self.more_btn.setText("⋯")
        self.more_btn.setToolTip("Más opciones")
        self.more_btn.setAccessibleName("Más opciones")
        self.more_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_btn.setMenu(menu)
        lay.addWidget(self.more_btn)


class Banner(QFrame):
    """Aviso dentro de la ventana (reemplaza a los diálogos modales)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setProperty("kind", "info")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 8, 8)
        lay.setSpacing(10)
        self.text = QLabel("")
        self.text.setWordWrap(True)
        lay.addWidget(self.text, 1)
        self.button = QPushButton("")
        self.button.clicked.connect(self._on_button)
        lay.addWidget(self.button)
        self.close_btn = QToolButton()
        self.close_btn.setObjectName("RowAction")
        self.close_btn.setText("✕")
        self.close_btn.setToolTip("Cerrar aviso")
        self.close_btn.clicked.connect(self.hide)
        lay.addWidget(self.close_btn)
        self._action = None
        self.hide()

    def show_message(self, text, kind="info", button=None, action=None, closable=True):
        self.text.setText(text)
        self.setProperty("kind", kind)
        repolish(self)
        self._action = action
        self.button.setVisible(bool(button and action))
        if button:
            self.button.setText(button)
        self.close_btn.setVisible(closable)
        self.show()

    def _on_button(self):
        if self._action:
            self._action()


class Popover(QFrame):
    """Ventanita que se abre debajo de un control y se cierra al hacer clic afuera."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.body = QFrame()
        self.body.setObjectName("PopoverBody")
        outer.addWidget(self.body)
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(14, 12, 14, 14)
        self.content.setSpacing(10)

    def open_below(self, anchor: QWidget):
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
        screen = anchor.screen().availableGeometry()
        x = min(pos.x(), screen.right() - self.width())
        y = pos.y() if pos.y() + self.height() <= screen.bottom() else anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 4
        self.move(max(screen.left(), x), y)
        self.show()


class Chip(QFrame):
    """Opción compacta: punteada si está apagada, rellena con su valor si está activa.

    Clic abre su popover; la × la vuelve a su valor por defecto.
    """

    cleared = Signal()

    def __init__(self, idle_text: str, popover: Popover, parent=None):
        super().__init__(parent)
        self.setObjectName("Chip")
        self._idle_text = idle_text
        self.popover = popover
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.button = QToolButton()
        self.button.setObjectName("ChipButton")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(lambda: self.popover.open_below(self))
        lay.addWidget(self.button)
        self.clear_btn = QToolButton()
        self.clear_btn.setObjectName("ChipClear")
        self.clear_btn.setText("×")
        self.clear_btn.setToolTip("Quitar")
        self.clear_btn.clicked.connect(self.cleared)
        lay.addWidget(self.clear_btn)
        self.set_value(None)

    def set_value(self, text: str | None, clearable: bool = True):
        active = bool(text)
        self.button.setText(text if active else self._idle_text)
        self.clear_btn.setVisible(active and clearable)
        # Sin × el botón necesita el margen derecho que daba la ×.
        self.button.setStyleSheet("" if active and clearable else "padding-right: 12px;")
        self.setProperty("active", "true" if active else "false")
        repolish(self)


class FlowLayout(QLayout):
    """Acomoda los widgets en filas y pasa a la siguiente cuando no caben (ejemplo oficial de Qt)."""

    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + self._spacing
            if next_x - self._spacing > rect.right() + 1 and line_h > 0:
                x, y = rect.x(), y + line_h + self._spacing
                next_x = x + hint.width() + self._spacing
                line_h = 0
            if not test:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class ElidedLabel(QLabel):
    """Etiqueta de una línea que recorta con «…» y muestra el texto completo al pasar el mouse."""

    def __init__(self, text="", parent=None, mode=Qt.TextElideMode.ElideRight):
        super().__init__(parent)
        self._full = ""
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text):
        self._full = text or ""
        self.setToolTip(self._full if len(self._full) > 40 else "")
        self._refresh()

    def full_text(self):
        return self._full

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh()

    def _refresh(self):
        w = max(10, self.width())
        super().setText(self.fontMetrics().elidedText(self._full, self._mode, w))


def hspacer() -> QWidget:
    w = QWidget()
    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return w
