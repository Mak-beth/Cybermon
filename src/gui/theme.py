"""CyberMon theme system.

Two palette dicts: LIGHT (default) and DARK.
Module-level active theme is maintained so any widget constructed after a
theme change (e.g. DetailPanel, which is built fresh on every row click)
automatically uses the correct colours without needing a MainWindow reference.

Usage
-----
    from src.gui import theme

    theme.set_active("dark")          # switch active theme
    palette = theme.get_active()      # read current palette dict
    css = theme.build_app_stylesheet(palette)  # global Qt stylesheet
"""
from __future__ import annotations

LIGHT: dict = {
    "sidebar_bg":     "#1e1e2e",   # sidebar stays dark in both themes
    "sidebar_text":   "#e2e8f0",
    "content_bg":     "#f8f9fa",
    "card_bg":        "#ffffff",
    "text_primary":   "#1e1e2e",
    "text_secondary": "#6b7280",
    "border":         "#e2e8f0",
    "input_bg":       "#ffffff",
    "table_alt":      "#f8fafc",
    "table_selected": "#ede9fe",
    "table_text":     "#1e1e2e",
}

DARK: dict = {
    "sidebar_bg":     "#111827",
    "sidebar_text":   "#e2e8f0",
    "content_bg":     "#1e1e2e",
    "card_bg":        "#2d2d3f",
    "text_primary":   "#f1f5f9",
    "text_secondary": "#9ca3af",
    "border":         "#374151",
    "input_bg":       "#374151",
    "table_alt":      "#252538",
    "table_selected": "#4c1d95",
    "table_text":     "#f1f5f9",
}


def get_theme(name: str) -> dict:
    """Return the palette dict for the given theme name."""
    return DARK if name == "dark" else LIGHT


# ---------------------------------------------------------------------------
# Module-level active theme
# ---------------------------------------------------------------------------
_active_name: str = "light"
_active: dict = LIGHT


def set_active(name: str) -> None:
    """Set the module-level active theme (light or dark)."""
    global _active_name, _active
    _active_name = "dark" if name == "dark" else "light"
    _active = get_theme(_active_name)


def get_active() -> dict:
    return _active


def get_active_name() -> str:
    return _active_name


# ---------------------------------------------------------------------------
# Global Qt stylesheet — acts as a fallback for widgets not explicitly styled
# ---------------------------------------------------------------------------

def build_app_stylesheet(palette: dict) -> str:
    bg    = palette["content_bg"]
    card  = palette["card_bg"]
    text  = palette["text_primary"]
    muted = palette["text_secondary"]
    bdr   = palette["border"]
    inp   = palette["input_bg"]
    return f"""
        QWidget            {{ background-color: {bg};   color: {text}; }}
        QLabel             {{ color: {text};             background: transparent; }}
        QDialog            {{ background-color: {card}; color: {text}; }}
        QScrollArea        {{ background-color: {bg};   border: none; }}
        QScrollBar:vertical {{
            background: {card}; width: 8px; border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: {bdr}; border-radius: 4px; min-height: 20px;
        }}
        QFrame             {{ background-color: {bg}; }}
        QTabWidget::pane   {{ background: {bg}; border: 1px solid {bdr}; }}
        QTabBar::tab       {{
            background: {card}; color: {muted};
            padding: 6px 18px; border-radius: 2px;
        }}
        QTabBar::tab:selected {{ background: #7c3aed; color: white; }}
        QLineEdit, QSpinBox, QTimeEdit {{
            background: {inp};
            color: {text};
            border: 1px solid {bdr};
            border-radius: 4px;
            padding: 4px 8px;
            selection-background-color: #7c3aed;
            selection-color: white;
        }}
        QComboBox {{
            background: {inp};
            color: {text};
            border: 1px solid {bdr};
            border-radius: 4px;
            padding: 4px 8px;
            padding-right: 28px;
            selection-background-color: #7c3aed;
            selection-color: white;
        }}
        QComboBox::drop-down {{
            subcontrol-origin: border;
            subcontrol-position: right center;
            width: 24px;
            border-left: 1px solid {bdr};
            border-top-right-radius: 4px;
            border-bottom-right-radius: 4px;
            background: {card};
        }}
        QComboBox::drop-down:hover   {{ background: {bdr}; }}
        QComboBox::drop-down:pressed {{ background: {muted}; }}
        QComboBox::down-arrow {{
            width: 10px;
            height: 10px;
        }}
        QComboBox QAbstractItemView {{
            background: {card};
            color: {text};
            border: 1px solid {bdr};
            selection-background-color: #7c3aed;
            selection-color: white;
            outline: none;
        }}
        QCheckBox          {{ color: {text}; background: transparent; }}
        QCheckBox::indicator {{
            width: 14px; height: 14px;
            border: 1px solid {bdr};
            border-radius: 3px;
            background: {inp};
        }}
        QCheckBox::indicator:checked {{
            background: #7c3aed; border-color: #7c3aed;
        }}
        QProgressBar {{
            background: {bdr}; border-radius: 5px; border: none;
        }}
        QTextEdit {{
            background: {card}; color: {text};
            border: 1px solid {bdr}; border-radius: 4px;
        }}
        QMessageBox {{ background: {card}; color: {text}; }}
        QToolTip    {{ background: {card}; color: {text}; border: 1px solid {bdr}; }}
    """
