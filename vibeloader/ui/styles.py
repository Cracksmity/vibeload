"""Tokens de color (claro/oscuro) y hoja de estilos Qt.

Un solo acento de marca (Vibe Violet) y colores de estado que significan algo:
verde = listo, rojo = error, ámbar = aviso. Contrastes medidos con WCAG 2.2:
texto blanco sobre el acento 5,8:1; texto atenuado sobre el fondo ≥ 6,3:1;
bordes de controles ≥ 3:1.
"""

THEMES = {
    "dark": {
        "bg": "#0F0D16",
        "surface": "#18151F",
        "surface_2": "#221E2C",
        "line": "#2E2939",
        "line_strong": "#6E6782",
        "text": "#F2EFF8",
        "text_dim": "#A39DB3",
        "accent": "#6D3DF2",
        "accent_hover": "#7C52F5",
        "accent_pressed": "#5B2CD9",
        "accent_soft": "#B69CFF",  # links, foco e íconos sobre el fondo
        "accent_tint": "#2A2240",  # fondo de chips activos y selección
        "success": "#3DD68C",
        "error": "#FF6B7A",
        "warning": "#FFB547",
        "success_bg": "#11261C",
        "error_bg": "#2C1419",
        "warning_bg": "#2A2010",
    },
    "light": {
        "bg": "#F7F5FB",
        "surface": "#FFFFFF",
        "surface_2": "#EFEBF7",
        "line": "#DCD6E8",
        "line_strong": "#8E86A0",
        "text": "#16131D",
        "text_dim": "#5E5770",
        "accent": "#6D3DF2",
        "accent_hover": "#7C52F5",
        "accent_pressed": "#5B2CD9",
        "accent_soft": "#5B2CD9",
        "accent_tint": "#E9E2FF",
        "success": "#13824F",
        "error": "#C8283B",
        "warning": "#8F5300",
        "success_bg": "#E3F5EC",
        "error_bg": "#FBE7EA",
        "warning_bg": "#FFF1DC",
    },
}

FONT_STACK = '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif'
MONO_STACK = '"Cascadia Mono", Consolas, monospace'


def build_stylesheet(theme_name: str) -> str:
    t = THEMES.get(theme_name, THEMES["dark"])
    return f"""
        QWidget {{
            background-color: transparent;
            color: {t['text']};
            font-family: {FONT_STACK};
            font-size: 14px;
        }}
        QMainWindow, QDialog, QWidget#Root {{ background-color: {t['bg']}; }}
        QToolTip {{
            background-color: {t['surface_2']}; color: {t['text']};
            border: 1px solid {t['line_strong']}; padding: 4px 8px; border-radius: 6px;
        }}

        /* ---------- Campos ---------- */
        QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {{
            background-color: {t['surface']};
            color: {t['text']};
            border: 1px solid {t['line_strong']};
            border-radius: 8px;
            padding: 6px 10px;
            selection-background-color: {t['accent']};
            selection-color: white;
        }}
        QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{ border: 2px solid {t['accent_soft']}; padding: 5px 9px; }}
        QLineEdit:disabled, QComboBox:disabled {{ color: {t['text_dim']}; border-color: {t['line']}; }}
        QComboBox QAbstractItemView {{
            background-color: {t['surface']}; border: 1px solid {t['line_strong']};
            selection-background-color: {t['accent_tint']}; selection-color: {t['text']};
            outline: none; padding: 4px;
        }}

        /* ---------- Botones ---------- */
        QPushButton {{
            background-color: {t['accent']};
            color: white;
            border: none;
            border-radius: 8px;
            padding: 7px 16px;
            font-weight: 600;
        }}
        QPushButton:hover {{ background-color: {t['accent_hover']}; }}
        QPushButton:pressed {{ background-color: {t['accent_pressed']}; }}
        QPushButton:focus {{ outline: none; }}
        QPushButton:disabled {{ background-color: {t['surface_2']}; color: {t['text_dim']}; }}
        QPushButton#secondary {{
            background-color: transparent;
            color: {t['text']};
            border: 1px solid {t['line_strong']};
        }}
        QPushButton#secondary:hover {{ background-color: {t['surface_2']}; }}
        QPushButton#secondary:disabled {{ color: {t['text_dim']}; border-color: {t['line']}; }}
        QPushButton#ghost {{ background-color: transparent; color: {t['accent_soft']}; padding: 7px 10px; }}
        QPushButton#ghost:hover {{ background-color: {t['surface_2']}; }}
        QPushButton#primary:focus, QPushButton#secondary:focus, QPushButton#ghost:focus,
        QPushButton#choicePrimary:focus, QPushButton#choiceAlt:focus {{
            border: 2px solid {t['accent_soft']};
        }}

        QToolButton {{
            background-color: transparent;
            color: {t['text']};
            border: 1px solid {t['line']};
            border-radius: 8px;
            padding: 6px 12px;
        }}
        QToolButton:hover {{ background-color: {t['surface_2']}; }}
        QToolButton:focus {{ border: 2px solid {t['accent_soft']}; }}
        QToolButton::menu-indicator {{ image: none; width: 0px; }}

        QCheckBox {{ spacing: 8px; }}
        QCheckBox::indicator {{
            width: 16px; height: 16px; border-radius: 4px;
            border: 1px solid {t['line_strong']}; background: {t['surface']};
        }}
        QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}

        /* ---------- Menús ---------- */
        QMenu {{
            background-color: {t['surface']};
            border: 1px solid {t['line_strong']};
            border-radius: 8px;
            padding: 6px;
        }}
        QMenu::item {{ padding: 7px 28px 7px 12px; border-radius: 6px; }}
        QMenu::item:selected {{ background-color: {t['accent_tint']}; }}
        QMenu::item:disabled {{ color: {t['text_dim']}; }}
        QMenu::separator {{ height: 1px; background: {t['line']}; margin: 5px 6px; }}
        QMenu::indicator {{ width: 14px; height: 14px; left: 6px; }}

        /* ---------- Cabecera ---------- */
        QFrame#Header {{ border-bottom: 1px solid {t['line']}; }}
        QLabel#Wordmark {{ font-size: 16px; font-weight: 700; }}
        QToolButton#HeaderButton {{ border: 1px solid {t['line']}; padding: 5px 12px; }}
        QToolButton#MoreButton {{ border: 1px solid {t['line']}; padding: 0px 10px 4px 10px; font-size: 20px; font-weight: 700; }}
        QFrame#Segmented {{
            background-color: {t['surface']};
            border: 1px solid {t['line']};
            border-radius: 9px;
        }}
        QPushButton#SegButton {{
            background-color: transparent; color: {t['text_dim']};
            border: none; border-radius: 7px; padding: 4px 12px; font-weight: 600;
        }}
        QPushButton#SegButton:hover {{ color: {t['text']}; background-color: transparent; }}
        QPushButton#SegButton:checked {{ background-color: {t['surface_2']}; color: {t['text']}; }}
        QPushButton#SegButton:focus {{ color: {t['accent_soft']}; }}

        /* ---------- Avisos (banner) ---------- */
        QFrame#Banner {{ border-radius: 10px; border: 1px solid {t['line']}; background-color: {t['surface']}; }}
        QFrame#Banner[kind="warn"] {{ background-color: {t['warning_bg']}; border-color: {t['warning']}; }}
        QFrame#Banner[kind="error"] {{ background-color: {t['error_bg']}; border-color: {t['error']}; }}
        QFrame#Banner[kind="ok"] {{ background-color: {t['success_bg']}; border-color: {t['success']}; }}
        QFrame#Banner QLabel {{ background: transparent; }}

        /* ---------- Progreso ---------- */
        QProgressBar {{
            background-color: {t['surface_2']};
            border: none;
            border-radius: 4px;
            max-height: 8px; min-height: 8px;
            text-align: center;
            color: transparent;
        }}
        QProgressBar::chunk {{ background-color: {t['accent']}; border-radius: 4px; }}
        QProgressBar#thin {{ max-height: 5px; min-height: 5px; border-radius: 2px; }}
        QProgressBar#thin::chunk {{ border-radius: 2px; }}
        QProgressBar[state="error"]::chunk {{ background-color: {t['error']}; }}
        QProgressBar[state="ok"]::chunk {{ background-color: {t['success']}; }}

        /* ---------- Texto ---------- */
        QLabel#Dim, QLabel#Meta {{ color: {t['text_dim']}; }}
        QLabel#Meta {{ font-size: 13px; }}
        QLabel#Hint {{ color: {t['text_dim']}; font-size: 13px; }}
        QLabel#Hint[kind="error"] {{ color: {t['error']}; }}
        QLabel#Hint a, QLabel#Meta a {{ color: {t['accent_soft']}; }}
        QLabel#Strong {{ font-weight: 600; }}

        /* ---------- Modo Simple ---------- */
        QWidget#SimpleView QLabel {{ font-size: 15px; }}
        QWidget#SimpleView QLabel#PreviewTitle {{ font-size: 16px; font-weight: 600; }}
        QWidget#SimpleView QLabel#Hint, QWidget#SimpleView QLabel#Meta {{ font-size: 14px; }}
        QWidget#SimpleView QPushButton {{ font-size: 15px; padding: 9px 18px; }}
        QLineEdit#bigUrl {{
            font-size: 17px;
            padding: 13px 14px;
            border: 2px solid {t['line_strong']};
            border-radius: 12px;
        }}
        QLineEdit#bigUrl:focus {{ border: 2px solid {t['accent_soft']}; padding: 13px 14px; }}
        QLineEdit#bigUrl[drop="true"] {{ border: 2px dashed {t['accent_soft']}; }}
        QFrame#Preview {{ background-color: {t['surface']}; border: 1px solid {t['line']}; border-radius: 12px; }}
        QFrame#Preview[state="empty"] {{ background-color: transparent; border: 1px dashed {t['line_strong']}; }}
        QFrame#Preview QLabel {{ background: transparent; }}
        QLabel#Thumb {{ background-color: {t['surface_2']}; border-radius: 7px; }}
        QPushButton#choicePrimary, QPushButton#choiceAlt {{
            border-radius: 12px; min-height: 80px; padding: 0px; text-align: left;
        }}
        QPushButton#choicePrimary {{ background-color: {t['accent']}; border: 2px solid {t['accent']}; }}
        QPushButton#choicePrimary:hover {{ background-color: {t['accent_hover']}; border-color: {t['accent_hover']}; }}
        QPushButton#choicePrimary:pressed {{ background-color: {t['accent_pressed']}; }}
        QPushButton#choiceAlt {{ background-color: {t['surface']}; border: 2px solid {t['line_strong']}; }}
        QPushButton#choiceAlt:hover {{ background-color: {t['surface_2']}; }}
        QPushButton#choicePrimary QLabel {{ color: white; background: transparent; }}
        QPushButton#choiceAlt QLabel {{ color: {t['text']}; background: transparent; }}
        QWidget#SimpleView QLabel#ChoiceTitle {{ font-size: 19px; font-weight: 700; }}
        QWidget#SimpleView QLabel#ChoiceSub {{ font-size: 14px; }}
        QWidget#SimpleView QLabel#ChoiceIcon {{
            font-family: "Segoe UI Symbol", {FONT_STACK}; font-size: 18px; border-radius: 10px;
            min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px;
        }}
        QPushButton#choicePrimary QLabel#ChoiceIcon {{ background-color: rgba(255, 255, 255, 40); }}
        QPushButton#choiceAlt QLabel#ChoiceIcon {{ background-color: {t['surface_2']}; color: {t['accent_soft']}; }}
        QToolButton#MoreFormats {{ border: none; color: {t['accent_soft']}; font-weight: 600; padding: 4px 2px; font-size: 14px; }}
        QToolButton#MoreFormats:hover {{ background: transparent; text-decoration: underline; }}
        QFrame#StatusStrip {{ background-color: {t['surface']}; border-top: 1px solid {t['line']}; }}
        QFrame#StatusStrip QLabel {{ background: transparent; }}
        QLabel#StatusTitle {{ font-weight: 600; }}
        QLabel#StatusDot {{
            min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px;
            border-radius: 15px; font-weight: 700; font-size: 15px;
        }}
        QLabel#StatusDot[kind="ok"] {{ background-color: {t['success_bg']}; color: {t['success']}; }}
        QLabel#StatusDot[kind="error"] {{ background-color: {t['error_bg']}; color: {t['error']}; }}

        /* ---------- Modo Avanzado ---------- */
        QFrame#Chip {{
            background-color: transparent;
            border: 1px dashed {t['line_strong']};
            border-radius: 15px;
        }}
        QFrame#Chip[active="true"] {{ background-color: {t['accent_tint']}; border: 1px solid {t['accent']}; }}
        QToolButton#ChipButton {{ border: none; background: transparent; padding: 4px 4px 4px 12px; color: {t['text_dim']}; font-size: 13px; }}
        QFrame#Chip[active="true"] QToolButton#ChipButton {{ color: {t['text']}; }}
        QToolButton#ChipButton:hover {{ color: {t['text']}; background: transparent; }}
        QToolButton#ChipClear {{ border: none; background: transparent; padding: 2px 10px 2px 4px; color: {t['text_dim']}; }}
        QToolButton#ChipClear:hover {{ color: {t['error']}; background: transparent; }}
        QFrame#PopoverBody {{
            background-color: {t['surface']};
            border: 1px solid {t['line_strong']};
            border-radius: 10px;
        }}
        QFrame#PopoverBody QLabel {{ background: transparent; }}
        QLabel#PopoverTitle {{ font-weight: 600; }}
        QFrame#Field {{ background-color: {t['surface']}; border: 1px solid {t['line']}; border-radius: 8px; }}
        QLabel#FieldLabel {{ color: {t['text_dim']}; font-size: 13px; padding-left: 2px; }}
        QComboBox#FieldCombo {{ border: none; background: transparent; padding: 4px 6px; }}
        QComboBox#FieldCombo:focus {{ border: none; }}
        QPushButton#FolderButton {{
            border: 1px solid {t['line']}; background-color: {t['surface']}; color: {t['text']};
            text-align: left; padding: 6px 28px 6px 10px; font-weight: 400;
        }}
        QPushButton#FolderButton:hover {{ background-color: {t['surface_2']}; }}
        QPushButton#FolderButton::menu-indicator {{ subcontrol-origin: padding; subcontrol-position: right center; right: 10px; }}

        QTabWidget::pane {{ border: none; border-top: 1px solid {t['line']}; }}
        QTabBar::tab {{
            background: transparent; color: {t['text_dim']};
            padding: 7px 2px; margin-right: 18px; border: none;
            font-size: 13px;
        }}
        QTabBar::tab:selected {{ color: {t['text']}; font-weight: 600; border-bottom: 2px solid {t['accent']}; }}
        QTabBar::tab:hover {{ color: {t['text']}; }}
        QListWidget#Queue {{ background: transparent; border: none; outline: none; }}
        QListWidget#Queue::item {{ border: none; padding: 0px; }}
        QListWidget#Queue::item:selected, QListWidget#Queue::item:hover {{ background: transparent; }}
        QFrame#QueueRow {{ border-radius: 8px; background: transparent; }}
        QFrame#QueueRow:hover, QFrame#QueueRow[active="true"] {{ background-color: {t['surface']}; }}
        QFrame#QueueRow QLabel {{ background: transparent; }}
        QLabel#RowTitle {{ font-weight: 600; }}
        QLabel#RowMeta {{ color: {t['text_dim']}; font-size: 13px; }}
        QLabel#RowStatus {{ color: {t['text_dim']}; font-size: 12px; font-family: {MONO_STACK}; }}
        QLabel#RowStatus[kind="ok"] {{ color: {t['success']}; font-family: {FONT_STACK}; font-weight: 600; }}
        QLabel#RowStatus[kind="error"] {{ color: {t['error']}; font-family: {FONT_STACK}; font-weight: 600; }}
        QToolButton#RowAction {{ border: none; color: {t['text_dim']}; padding: 4px 8px; }}
        QToolButton#RowAction:hover {{ color: {t['text']}; background-color: {t['surface_2']}; }}
        QLabel#EmptyQueue {{ color: {t['text_dim']}; }}
        QTextEdit#Log {{
            font-family: {MONO_STACK}; font-size: 12px;
            border: none; background: transparent; padding: 6px 0px;
        }}
        QFrame#Footer {{ border-top: 1px solid {t['line']}; }}
        QLabel#FooterText {{ color: {t['text_dim']}; font-family: {MONO_STACK}; font-size: 12px; }}

        /* ---------- Tablas (historial) ---------- */
        QTableWidget, QListWidget {{
            background-color: {t['surface']};
            border: 1px solid {t['line']};
            border-radius: 8px;
            gridline-color: {t['line']};
            selection-background-color: {t['accent_tint']};
            selection-color: {t['text']};
            outline: none;
        }}
        QHeaderView::section {{
            background-color: {t['surface_2']}; color: {t['text_dim']};
            border: none; padding: 6px 8px; font-size: 12px; font-weight: 600;
        }}

        /* ---------- Barras de desplazamiento ---------- */
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {t['line_strong']}; border-radius: 3px; min-height: 30px; }}
        QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
        QScrollBar::handle:horizontal {{ background: {t['line_strong']}; border-radius: 3px; min-width: 30px; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    """
