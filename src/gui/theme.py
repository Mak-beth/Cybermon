"""CyberMon theme system — single source of truth for all UI colours.

Design
------
Every colour lives here. Widgets must NOT call setStyleSheet with hardcoded
colours: they set an objectName and the rules below style them, so a theme
switch re-styles them automatically even when no Python reference to the widget
was kept (the bug that left small Overview text dark-on-dark).

Anything Qt stylesheets cannot reach — PyQtGraph internals, custom QPainter
widgets — registers a hook via register_chart() and is re-themed in code.

Usage
-----
    from src.gui import theme

    theme.apply_theme(dark=True)      # restyle whole app + charts + persist
    theme.load_saved_theme()          # -> bool, read persisted choice at startup
    palette = theme.get_active()      # current palette dict
"""
from __future__ import annotations

import logging
import os
import tempfile

from PyQt6.QtCore import QPoint, QSettings, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap, QPolygon
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

_SETTINGS_ORG = "CyberMon"
_SETTINGS_APP = "CyberMon"
_SETTINGS_KEY = "ui/theme"

# Brand accent — identical in both themes.
ACCENT       = "#7c3aed"
ACCENT_HOVER = "#6d28d9"
ACCENT_DOWN  = "#5b21b6"

# Semantic severity colours — deliberately theme-invariant so a Critical badge
# looks the same in light and dark. Never fold these into a palette.
SEVERITY: dict = {
    "Critical": "#7f1d1d",
    "High":     "#ef4444",
    "Medium":   "#f59e0b",
    "Low":      "#22c55e",
}

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


def is_dark() -> bool:
    """True when the dark theme is active. Prefer this over identity checks
    against the DARK dict, which break if a palette is ever copied/rebuilt."""
    return _active_name == "dark"


# ---------------------------------------------------------------------------
# Chart hooks — for anything QSS cannot reach (PyQtGraph, QPainter widgets)
# ---------------------------------------------------------------------------
_chart_hooks: list = []


def register_chart(hook) -> None:
    """Register callable(palette) to be invoked on every theme change."""
    _chart_hooks.append(hook)


def _retheme_charts(palette: dict) -> None:
    for hook in list(_chart_hooks):
        try:
            hook(palette)
        except Exception:
            # Non-fatal: a deleted widget must never break the toggle. Logged
            # (not swallowed) so failures are visible during testing.
            logger.warning("theme: chart re-theme hook failed", exc_info=True)


# ---------------------------------------------------------------------------
# Arrow glyphs for spin / time / combo sub-controls
#
# Once a widget is styled by QSS, Qt stops drawing its native sub-control
# arrows, and QSS has no way to draw a shape (the CSS border-triangle trick
# paints a filled box in Qt). The only reliable option is a real image, so the
# triangles are painted with QPainter at run time — the same approach already
# used for the window's shield icon — and cached per colour.
# ---------------------------------------------------------------------------
_ARROW_CACHE: dict = {}


def _arrow_image(direction: str, colour: str) -> str:
    """Return a filesystem path to a small triangle PNG in the given colour."""
    key = (direction, colour)
    cached = _ARROW_CACHE.get(key)
    if cached and os.path.exists(cached):
        return cached

    size = 16                      # drawn 2x, displayed at 8px for crispness
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(colour))
    painter.setPen(Qt.PenStyle.NoPen)
    m = 3
    if direction == "up":
        pts = [QPoint(size // 2, m), QPoint(size - m, size - m), QPoint(m, size - m)]
    else:
        pts = [QPoint(m, m), QPoint(size - m, m), QPoint(size // 2, size - m)]
    painter.drawPolygon(QPolygon(pts))
    painter.end()

    out_dir = os.path.join(tempfile.gettempdir(), "cybermon_theme")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"arrow_{direction}_{colour.lstrip('#')}.png")
    pm.save(path, "PNG")
    _ARROW_CACHE[key] = path
    return path


def _arrow_url(direction: str, colour: str) -> str:
    """QSS url() for an arrow glyph; empty string if it cannot be generated."""
    try:
        return _arrow_image(direction, colour).replace("\\", "/")
    except Exception:
        # No QGuiApplication yet, or read-only temp dir — fall back to no image.
        logger.warning("theme: could not generate arrow glyph", exc_info=True)
        return ""


# ---------------------------------------------------------------------------
# The single app-wide stylesheet
# ---------------------------------------------------------------------------

def build_app_stylesheet(palette: dict) -> str:
    """Return the complete Qt stylesheet for the given palette."""
    bg    = palette["content_bg"]
    card  = palette["card_bg"]
    text  = palette["text_primary"]
    muted = palette["text_secondary"]
    bdr   = palette["border"]
    inp   = palette["input_bg"]
    alt   = palette["table_alt"]
    sel   = palette["table_selected"]
    side  = palette["sidebar_bg"]

    up_arrow   = _arrow_url("up", text)
    down_arrow = _arrow_url("down", text)

    return f"""
    /* ---------- base ---------- */
    QWidget  {{ background-color: {bg}; color: {text}; }}
    QLabel   {{ color: {text}; background: transparent; }}
    QDialog, QMessageBox {{ background-color: {card}; color: {text}; }}
    QMainWindow, QStackedWidget {{ background-color: {bg}; }}

    /* ---------- named labels (reachable without a stored reference) ---------- */
    QLabel#panelTitle     {{ color: {text};  font-size: 18px; font-weight: bold; }}
    QLabel#sectionTitle   {{ color: {text};  font-size: 13px; font-weight: bold; border: none; }}
    QLabel#sectionHeader  {{ color: {muted}; font-size: 11px; font-weight: bold;
                             letter-spacing: 0.5px; }}
    QLabel#fieldLabel     {{ color: {text};  font-size: 13px; }}
    QLabel#metricTitle    {{ color: {muted}; font-size: 12px; border: none; }}
    QLabel#breakdownLabel {{ color: {text};  font-size: 12px; border: none; }}
    QLabel#breakdownCount {{ color: {text};  font-size: 13px; font-weight: bold; border: none; }}
    QLabel#legendText     {{ color: {text};  font-size: 11px; border: none; }}
    QLabel#chartTitle     {{ color: {text};  font-size: 13px; font-weight: bold; border: none; }}
    QLabel#lastUpdated    {{ color: {muted}; font-size: 12px; }}
    QLabel#mutedText      {{ color: {muted}; font-size: 12px; }}
    QLabel#emptyState     {{ color: {muted}; font-size: 15px; }}

    /* ---------- cards / frames ---------- */
    QFrame#card {{
        background: {card}; border: 1px solid {bdr}; border-radius: 6px;
    }}
    QFrame#divider {{ color: {bdr}; background: {bdr}; border: none; }}

    /* ---------- buttons ---------- */
    QPushButton#primary {{
        background: {ACCENT}; color: white; border: none;
        border-radius: 4px; padding: 6px 12px; font-size: 13px;
    }}
    QPushButton#primary:hover   {{ background: {ACCENT_HOVER}; }}
    QPushButton#primary:pressed {{ background: {ACCENT_DOWN}; }}
    QPushButton#secondary {{
        background: {card}; color: {text}; border: 1px solid {bdr};
        border-radius: 4px; padding: 6px 12px; font-size: 13px;
    }}
    QPushButton#secondary:hover {{ background: {bdr}; }}

    /* settings panel uses its own long-standing object names */
    QLabel#section {{
        color: {muted}; font-size: 11px; font-weight: bold; letter-spacing: 0.5px;
    }}
    QWidget#settings_root {{ background: {bg}; }}
    QPushButton#save {{
        background: {ACCENT}; color: white; border: none; border-radius: 4px;
        padding: 8px 20px; font-size: 13px; font-weight: bold;
    }}
    QPushButton#save:hover {{ background: {ACCENT_HOVER}; }}
    QPushButton#rerun {{
        background: {card}; color: {muted}; border: 1px solid {bdr};
        border-radius: 4px; padding: 8px 20px; font-size: 13px;
    }}
    QPushButton#rerun:hover {{ background: {bdr}; }}
    /* Compact accent button for narrow fixed-width uses (e.g. 70px "Browse").
       The #save padding of 20px each side would clip the label. */
    QPushButton#browse {{
        background: {ACCENT}; color: white; border: none; border-radius: 4px;
        padding: 6px 4px; font-size: 12px; font-weight: bold;
    }}
    QPushButton#browse:hover {{ background: {ACCENT_HOVER}; }}

    /* ---------- inputs ---------- */
    QLineEdit, QSpinBox, QTimeEdit, QPlainTextEdit, QTextEdit {{
        background: {inp}; color: {text};
        border: 1px solid {bdr}; border-radius: 4px; padding: 4px 8px;
        selection-background-color: {ACCENT}; selection-color: white;
    }}
    QLineEdit:focus, QSpinBox:focus, QTimeEdit:focus,
    QPlainTextEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}

    QSpinBox::up-button, QTimeEdit::up-button {{
        subcontrol-origin: border; subcontrol-position: top right; width: 20px;
        border-left: 1px solid {bdr}; border-bottom: 1px solid {bdr};
        border-top-right-radius: 4px; background: {card};
    }}
    QSpinBox::down-button, QTimeEdit::down-button {{
        subcontrol-origin: border; subcontrol-position: bottom right; width: 20px;
        border-left: 1px solid {bdr}; border-top: 1px solid {bdr};
        border-bottom-right-radius: 4px; background: {card};
    }}
    QSpinBox::up-button:hover, QTimeEdit::up-button:hover,
    QSpinBox::down-button:hover, QTimeEdit::down-button:hover {{ background: {bdr}; }}

    /* Arrow glyphs. Styling ::up-button/::down-button suppresses Qt's native
       arrow, and QSS cannot draw a shape (border-triangles paint a filled box
       in Qt), so a generated PNG is supplied. Colour follows the palette. */
    QSpinBox::up-arrow, QTimeEdit::up-arrow {{
        image: url({up_arrow}); width: 8px; height: 8px;
    }}
    QSpinBox::down-arrow, QTimeEdit::down-arrow {{
        image: url({down_arrow}); width: 8px; height: 8px;
    }}

    /* ---------- combo box (closed box AND popup list) ---------- */
    QComboBox {{
        background: {inp}; color: {text}; border: 1px solid {bdr};
        border-radius: 4px; padding: 4px 8px; padding-right: 28px;
        selection-background-color: {ACCENT}; selection-color: white;
        /* Use the styled list popup rather than the native one, so the rules
           below actually apply and the popup cannot overflow its frame. */
        combobox-popup: 0;
    }}
    QComboBox::drop-down {{
        subcontrol-origin: border; subcontrol-position: right center; width: 24px;
        border-left: 1px solid {bdr};
        border-top-right-radius: 4px; border-bottom-right-radius: 4px;
        background: {card};
    }}
    QComboBox::drop-down:hover   {{ background: {bdr}; }}
    QComboBox::drop-down:pressed {{ background: {muted}; }}
    QComboBox::down-arrow {{
        image: url({down_arrow}); width: 10px; height: 10px;
    }}
    QComboBox::down-arrow:on {{ image: url({up_arrow}); }}
    /* Popup list. Both the view AND its items need rules: styling only the
       view leaves item text painted by the native palette (dark-on-dark). */
    QComboBox QAbstractItemView {{
        background: {card}; color: {text};
        border: 1px solid {bdr}; border-radius: 4px;
        selection-background-color: {ACCENT}; selection-color: white;
        outline: none; padding: 2px;
    }}
    QComboBox QAbstractItemView::item {{
        background: {card}; color: {text};
        min-height: 24px; padding: 4px 8px; border: none;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background: {ACCENT}; color: white;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background: {ACCENT}; color: white;
    }}

    /* ---------- tables & headers ---------- */
    QTableView, QTableWidget {{
        background: {card}; color: {text};
        alternate-background-color: {alt};
        gridline-color: {bdr}; border: 1px solid {bdr};
        font-size: 13px;
    }}
    QTableView::item:selected, QTableWidget::item:selected {{
        background: {sel}; color: {text};
    }}
    QHeaderView {{ background: {card}; }}
    QHeaderView::section {{
        background: {card}; color: {text}; font-weight: bold;
        padding: 6px; border: none; border-bottom: 2px solid {bdr};
    }}
    QTableCornerButton::section {{ background: {card}; border: none; }}

    /* ---------- group boxes ---------- */
    QGroupBox {{
        color: {text}; border: 1px solid {bdr}; border-radius: 6px;
        margin-top: 10px; padding-top: 10px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin; subcontrol-position: top left;
        left: 8px; padding: 0 4px; color: {muted};
    }}

    /* ---------- tabs ---------- */
    QTabWidget::pane {{ background: {bg}; border: 1px solid {bdr}; border-radius: 4px; }}
    QTabBar::tab {{
        background: {card}; color: {muted}; padding: 6px 18px; border-radius: 2px;
    }}
    QTabBar::tab:selected {{ background: {ACCENT}; color: white; }}

    /* ---------- scrollbars ---------- */
    QScrollArea {{ background-color: {bg}; border: none; }}
    QScrollBar:vertical   {{ background: {card}; width: 8px;  border-radius: 4px; }}
    QScrollBar:horizontal {{ background: {card}; height: 8px; border-radius: 4px; }}
    QScrollBar::handle:vertical   {{ background: {bdr}; border-radius: 4px; min-height: 20px; }}
    QScrollBar::handle:horizontal {{ background: {bdr}; border-radius: 4px; min-width: 20px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; border: none; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    /* ---------- misc ---------- */
    QCheckBox {{ color: {text}; background: transparent; }}
    QCheckBox::indicator {{
        width: 14px; height: 14px; border: 1px solid {bdr};
        border-radius: 3px; background: {inp};
    }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
    QProgressBar {{ background: {bdr}; border-radius: 5px; border: none; }}
    QToolTip {{
        background: {card}; color: {text}; border: 1px solid {bdr}; padding: 4px;
    }}

    /* ---------- sidebar (dark in both themes) ---------- */
    QFrame#sidebar {{ background-color: {side}; border: none; }}
    QFrame#sidebar QLabel {{ background: {side}; }}
    QLabel#sidebarTitle {{ color: {ACCENT}; font-size: 17px; font-weight: bold; }}
    QLabel#sidebarVersion {{ color: #4a4a6a; font-size: 11px; }}
    QFrame#sidebarDivider {{ color: #3d3d5c; background: #3d3d5c; border: none; }}
    QLabel#agentIndicator {{ color: {SEVERITY['High']}; font-size: 11px; padding: 4px 12px; }}
    QPushButton#navButton {{
        border: none; border-left: 4px solid transparent; background: transparent;
        color: {palette['sidebar_text']}; text-align: left;
        padding: 12px 16px; font-size: 14px;
    }}
    QPushButton#navButton:hover {{ background: rgba(124, 58, 237, 0.12); }}
    QPushButton#navButton:checked {{
        border-left: 4px solid {ACCENT}; background: rgba(124, 58, 237, 0.20);
        color: #ffffff; font-weight: bold;
    }}

    /* ---------- warning banner (fixed amber in both themes) ---------- */
    QFrame#warning_banner {{ background: #fef3c7; border-bottom: 1px solid #f59e0b; }}
    QFrame#warning_banner QLabel {{ background: transparent; color: #92400e; font-size: 13px; }}
    QLabel#bannerIcon {{ color: #d97706; font-size: 16px; font-weight: bold; }}
    QPushButton#bannerLink {{
        color: {ACCENT}; font-size: 13px; text-decoration: underline;
        border: none; background: transparent; padding: 0 4px;
    }}
    QPushButton#bannerDismiss {{
        color: #92400e; border: none; background: transparent; font-size: 14px;
    }}
    """


# ---------------------------------------------------------------------------
# Public entry point + persistence
# ---------------------------------------------------------------------------

def apply_theme(dark: bool) -> None:
    """Apply a theme app-wide: stylesheet, chart internals, and persist choice.

    Instant hard swap — no animation (standard Qt behaviour).
    """
    set_active("dark" if dark else "light")
    palette = get_active()

    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(build_app_stylesheet(palette))

    _retheme_charts(palette)

    try:
        QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue(_SETTINGS_KEY, get_active_name())
    except Exception:
        logger.warning("theme: could not persist theme preference", exc_info=True)


def load_saved_theme() -> bool:
    """Read the persisted theme preference. Returns True when dark.

    Stored in QSettings — a UI preference, deliberately kept out of
    config.yaml (which holds detection rules).
    """
    try:
        value = QSettings(_SETTINGS_ORG, _SETTINGS_APP).value(_SETTINGS_KEY, "light")
    except Exception:
        logger.warning("theme: could not read theme preference", exc_info=True)
        return False
    return str(value).lower() == "dark"
