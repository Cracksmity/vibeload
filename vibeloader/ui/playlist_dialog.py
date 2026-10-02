"""Elegir videos de una lista de reproducción para mandarlos a la cola."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ..config import preset_label
from ..utils import format_duration


class PlaylistDialog(QDialog):
    def __init__(self, parent, title: str, entries: list, presets, preset: str):
        super().__init__(parent)
        self.setWindowTitle("Lista de reproducción")
        self.resize(700, 560)
        self._entries = entries

        layout = QVBoxLayout(self)
        head = QLabel(f"<b>{title or 'Lista de reproducción'}</b> · {len(entries)} videos")
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setWordWrap(True)
        layout.addWidget(head)
        layout.addWidget(QLabel("Marca los videos que quieres descargar; se agregan a la cola."))

        self.list = QListWidget()
        for e in entries:
            dur = format_duration(e.get("duration"))
            text = e.get("title") or e.get("url")
            item = QListWidgetItem(f"{text}   ({dur})" if dur else text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(item)
        self.list.itemChanged.connect(self._update_count)
        layout.addWidget(self.list, 1)

        sel = QHBoxLayout()
        all_btn = QPushButton("Marcar todos")
        all_btn.setObjectName("secondary")
        all_btn.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        none_btn = QPushButton("Desmarcar todos")
        none_btn.setObjectName("secondary")
        none_btn.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        self.count_label = QLabel("")
        sel.addWidget(all_btn)
        sel.addWidget(none_btn)
        sel.addStretch()
        sel.addWidget(self.count_label)
        layout.addLayout(sel)

        opts = QHBoxLayout()
        opts.addWidget(QLabel("Formato:"))
        self.preset_combo = QComboBox()
        for p in presets:
            self.preset_combo.addItem(preset_label(p), p)
        idx = self.preset_combo.findData(preset)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
        opts.addWidget(self.preset_combo, 1)
        layout.addLayout(opts)

        self.subfolder_chk = QCheckBox("Guardar en una subcarpeta con el nombre de la lista")
        self.subfolder_chk.setChecked(True)
        layout.addWidget(self.subfolder_chk)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Agregar a la cola")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._update_count()

    def _set_all(self, state):
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(state)
        self.list.blockSignals(False)
        self._update_count()

    def _update_count(self, *_):
        n = len(self.selected_urls())
        self.count_label.setText(f"{n} seleccionados")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(n > 0)

    def selected_urls(self) -> list:
        return [
            self._entries[i]["url"]
            for i in range(self.list.count())
            if self.list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def preset(self) -> str:
        return self.preset_combo.currentData()

    def use_subfolder(self) -> bool:
        return self.subfolder_chk.isChecked()
