"""Diálogo de carpetas predeterminadas."""
import os

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..config import (
    PRESET_CAR,
    PRESET_CURSOS,
    PRESET_DIRECTO,
    PRESET_MAX,
    PRESET_MP3,
    PRESET_TAMANO,
    PRESET_WHATSAPP,
)


class DefaultFoldersConfigDialog(QDialog):
    ROWS = (
        (PRESET_WHATSAPP, "Videos para WhatsApp:"),
        (PRESET_MAX, "Videos en máxima calidad:"),
        (PRESET_MP3, "Música / MP3:"),
        (PRESET_CAR, "Videos para Modo Auto (autoestéreo):"),
        (PRESET_DIRECTO, "Videos en Modo Descarga Directa:"),
        (PRESET_CURSOS, "Videos en Modo Cursos (H.265):"),
        (PRESET_TAMANO, "Videos comprimidos a tamaño máximo:"),
    )

    def __init__(self, parent, paths: dict, first_run: bool = False):
        super().__init__(parent)
        self._edits = {}
        self.setWindowTitle(
            "Bienvenida — carpetas predeterminadas"
            if first_run
            else "Carpetas predeterminadas"
        )
        self.setMinimumWidth(620)

        layout = QVBoxLayout(self)
        if first_run:
            intro = QLabel(
                "Es la primera vez que abres VibeLoader. Elige dónde guardar "
                "los archivos de cada modo (puedes cambiarlo después)."
            )
            intro.setWordWrap(True)
            layout.addWidget(intro)

        for key, label_text in self.ROWS:
            layout.addWidget(QLabel(label_text))
            row = QHBoxLayout()
            edit = QLineEdit()
            edit.setText(paths.get(key, ""))
            browse = QPushButton("Examinar…")
            browse.clicked.connect(lambda _=False, e=edit: self._browse_folder(e))
            row.addWidget(edit)
            row.addWidget(browse)
            layout.addLayout(row)
            self._edits[key] = edit

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_folder(self, edit: QLineEdit):
        start = edit.text().strip() or os.path.expanduser("~")
        carpeta = QFileDialog.getExistingDirectory(self, "Elegir carpeta", start)
        if carpeta:
            edit.setText(carpeta)

    def _try_accept(self):
        for key, edit in self._edits.items():
            if not edit.text().strip():
                QMessageBox.warning(
                    self, "Falta una ruta", f"Indica una carpeta válida para «{key}»."
                )
                return
        self.accept()

    def get_paths(self) -> dict:
        return {k: e.text().strip() for k, e in self._edits.items()}
