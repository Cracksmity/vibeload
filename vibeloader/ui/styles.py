"""Temas claro/oscuro y hoja de estilos Qt."""

THEMES = {
    "dark": {
        "bg": "#15161c",
        "surface": "#1d1f29",
        "border": "#2c2f3d",
        "text": "#f4f5fb",
        "text_dim": "#a4abc2",
        "accent": "#7c83ff",
        "accent_hover": "#969cff",
        "music": "#7c83ff",
        "music_hover": "#969cff",
        "video": "#22c1c3",
        "video_hover": "#44d4d6",
        "car": "#ffb454",
        "car_hover": "#ffc274",
        "directo": "#a855f7",
        "directo_hover": "#c084fc",
        "success": "#4ade80",
        "error": "#fb7185",
        "title": "#ffeaa7",
    },
    "light": {
        "bg": "#fafbff",
        "surface": "#ffffff",
        "border": "#e1e4ee",
        "text": "#1d1f29",
        "text_dim": "#5b6479",
        "accent": "#5a64f0",
        "accent_hover": "#7079f4",
        "music": "#5a64f0",
        "music_hover": "#7079f4",
        "video": "#0ca7a8",
        "video_hover": "#1ec0c1",
        "car": "#e08e2a",
        "car_hover": "#eda43d",
        "directo": "#9333ea",
        "directo_hover": "#a855f7",
        "success": "#16a34a",
        "error": "#dc2626",
        "title": "#1d1f29",
    },
}


def build_stylesheet(theme_name: str) -> str:
    t = THEMES.get(theme_name, THEMES["dark"])
    return f"""
        QWidget {{
            background-color: {t['bg']};
            color: {t['text']};
            font-family: "Segoe UI Variable", "Segoe UI", system-ui, Arial, sans-serif;
            font-size: 11pt;
        }}
        QMainWindow {{
            background-color: {t['bg']};
        }}
        QLineEdit, QTextEdit, QComboBox {{
            background-color: {t['surface']};
            color: {t['text']};
            border: 1px solid {t['border']};
            border-radius: 8px;
            padding: 8px 10px;
            selection-background-color: {t['accent']};
        }}
        QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
            border: 1px solid {t['accent']};
        }}
        QPushButton {{
            background-color: {t['accent']};
            color: white;
            border: none;
            border-radius: 10px;
            padding: 8px 14px;
            font-weight: 600;
        }}
        QPushButton:hover {{ background-color: {t['accent_hover']}; }}
        QPushButton:disabled {{ background-color: {t['border']}; color: {t['text_dim']}; }}
        QPushButton#secondary {{
            background-color: transparent;
            color: {t['text']};
            border: 1px solid {t['border']};
        }}
        QPushButton#secondary:hover {{
            border: 1px solid {t['accent']};
            color: {t['accent']};
        }}
        QPushButton#big_music {{ background-color: {t['music']}; min-height: 64px; font-size: 13pt; }}
        QPushButton#big_music:hover {{ background-color: {t['music_hover']}; }}
        QPushButton#big_video {{ background-color: {t['video']}; min-height: 64px; font-size: 13pt; }}
        QPushButton#big_video:hover {{ background-color: {t['video_hover']}; }}
        QPushButton#big_car {{ background-color: {t['car']}; min-height: 64px; font-size: 13pt; }}
        QPushButton#big_car:hover {{ background-color: {t['car_hover']}; }}
        QPushButton#big_directo {{ background-color: {t['directo']}; min-height: 64px; font-size: 13pt; }}
        QPushButton#big_directo:hover {{ background-color: {t['directo_hover']}; }}
        QProgressBar {{
            background-color: {t['surface']};
            color: {t['text']};
            border: 1px solid {t['border']};
            border-radius: 8px;
            text-align: center;
            min-height: 26px;
            font-weight: 600;
        }}
        QProgressBar::chunk {{
            background-color: {t['video']};
            border-radius: 8px;
        }}
        QFrame#card_success {{
            background-color: {t['surface']};
            border: 1px solid {t['success']};
            border-radius: 10px;
        }}
        QFrame#card_error {{
            background-color: {t['surface']};
            border: 1px solid {t['error']};
            border-radius: 10px;
        }}
        QFrame#card_success QLabel, QFrame#card_error QLabel,
        QFrame#card_notice QLabel, QFrame#preview QLabel {{
            background: transparent;
        }}
        QFrame#card_notice {{
            background-color: {t['surface']};
            border: 1px solid {t['car']};
            border-radius: 10px;
        }}
        QFrame#preview {{
            background-color: {t['surface']};
            border: 1px solid {t['border']};
            border-radius: 10px;
        }}
        QLabel#TitleLabel {{
            font-size: 22pt;
            font-weight: 700;
            color: {t['title']};
        }}
        QLabel#SubtitleLabel {{
            font-size: 10pt;
            color: {t['text_dim']};
        }}
        QLabel#PreviewTitle {{
            font-size: 12pt;
            font-weight: 600;
            color: {t['text']};
        }}
        QLabel#PreviewMeta {{
            font-size: 10pt;
            color: {t['text_dim']};
        }}
        QLabel#FolderHint {{
            font-size: 9pt;
            color: {t['text_dim']};
        }}
        QLineEdit#bigUrl {{
            font-size: 13pt;
            padding: 14px 16px;
            min-height: 28px;
        }}
        QToolButton {{
            background: transparent;
            color: {t['text']};
            border: 1px solid {t['border']};
            border-radius: 8px;
            padding: 6px 10px;
        }}
        QToolButton:hover {{
            border: 1px solid {t['accent']};
            color: {t['accent']};
        }}
        QToolButton::menu-indicator {{ width: 0px; image: none; }}
    """
