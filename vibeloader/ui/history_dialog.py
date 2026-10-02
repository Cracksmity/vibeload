"""Diálogo con las últimas descargas: abrir archivo o carpeta."""
import os
import time

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..history import clear_history, load_history


class HistoryDialog(QDialog):
    def __init__(self, parent, settings):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Historial de descargas")
        self.resize(820, 460)

        layout = QVBoxLayout(self)
        self.empty_label = QLabel("Todavía no hay descargas en el historial.")
        layout.addWidget(self.empty_label)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Fecha", "Archivo", "Modo"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda _i: self._open_file())
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.open_file_btn = QPushButton("Abrir archivo")
        self.open_file_btn.clicked.connect(self._open_file)
        self.open_folder_btn = QPushButton("Abrir carpeta")
        self.open_folder_btn.setObjectName("secondary")
        self.open_folder_btn.clicked.connect(self._open_folder)
        self.clear_btn = QPushButton("Borrar historial")
        self.clear_btn.setObjectName("secondary")
        self.clear_btn.setToolTip("Solo borra la lista; los archivos no se tocan")
        self.clear_btn.clicked.connect(self._clear)
        close_btn = QPushButton("Cerrar")
        close_btn.setObjectName("secondary")
        close_btn.clicked.connect(self.accept)
        row.addWidget(self.open_file_btn)
        row.addWidget(self.open_folder_btn)
        row.addStretch()
        row.addWidget(self.clear_btn)
        row.addWidget(close_btn)
        layout.addLayout(row)

        self._entries = []
        self._reload()

    def _reload(self):
        self._entries = load_history(self.settings)
        self.table.setRowCount(len(self._entries))
        for r, e in enumerate(self._entries):
            when = time.strftime("%d/%m/%Y %H:%M", time.localtime(e.get("ts") or 0))
            name = e.get("title") or os.path.basename(e["path"])
            exists = os.path.exists(e["path"])
            items = [
                QTableWidgetItem(when),
                QTableWidgetItem(name if exists else f"{name}  (ya no existe)"),
                QTableWidgetItem(e.get("preset", "")),
            ]
            items[1].setToolTip(e["path"])
            for c, it in enumerate(items):
                if not exists:
                    it.setForeground(Qt.GlobalColor.gray)
                self.table.setItem(r, c, it)
        has = bool(self._entries)
        self.empty_label.setVisible(not has)
        self.table.setVisible(has)
        self.clear_btn.setEnabled(has)
        if has:
            self.table.selectRow(0)
        self._update_buttons()

    def _current(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        return self._entries[rows[0].row()]

    def _update_buttons(self):
        e = self._current()
        self.open_file_btn.setEnabled(bool(e and os.path.exists(e["path"])))
        self.open_folder_btn.setEnabled(bool(e and os.path.isdir(os.path.dirname(e["path"]))))

    def _open_file(self):
        e = self._current()
        if e and os.path.exists(e["path"]):
            QDesktopServices.openUrl(QUrl.fromLocalFile(e["path"]))

    def _open_folder(self):
        e = self._current()
        if e and os.path.isdir(os.path.dirname(e["path"])):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(e["path"])))

    def _clear(self):
        clear_history(self.settings)
        self._reload()
