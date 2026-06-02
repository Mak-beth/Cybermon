"""CyberMon main application window.

Builds the outer shell: sidebar navigation + QStackedWidget content area.
All other GUI panels (violations table, overview, live feed, etc.) are loaded
into the stack and swapped by clicking the sidebar items.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Palette constants
# ---------------------------------------------------------------------------
_SIDEBAR_BG      = "#1e1e2e"
_SIDEBAR_TEXT    = "#e2e8f0"
_ACCENT_PURPLE   = "#7c3aed"
_CONTENT_BG      = "#f8f9fa"

# Sidebar item order matches QStackedWidget index
_NAV_ITEMS = [
    "Overview",
    "Violations",
    "Live Feed",
    "Trend",
    "Settings",
]


# ---------------------------------------------------------------------------
# Shield icon (rendered programmatically — no external file needed)
# ---------------------------------------------------------------------------

def _make_shield_icon() -> QIcon:
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(_ACCENT_PURPLE))
    p.setPen(Qt.PenStyle.NoPen)
    path = QPainterPath()
    path.moveTo(16, 1)
    path.lineTo(30, 7)
    path.lineTo(30, 18)
    path.quadTo(30, 28, 16, 31)
    path.quadTo(2, 28, 2, 18)
    path.lineTo(2, 7)
    path.closeSubpath()
    p.drawPath(path)
    # Small white lock body
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(11, 16, 10, 8, 2, 2)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------
# Placeholder panel for panels not yet built
# ---------------------------------------------------------------------------

class _PlaceholderPanel(QWidget):
    def __init__(self, message: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel(message)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: #6b7280; font-size: 15px;")
        layout.addWidget(lbl)


# ---------------------------------------------------------------------------
# Sidebar button
# ---------------------------------------------------------------------------

class _SidebarButton(QPushButton):
    """Flat checkable button styled to match the sidebar design.

    When checked, a 4 px purple left border is drawn via stylesheet.
    """

    _STYLE_BASE = f"""
        QPushButton {{
            border: none;
            border-left: 4px solid transparent;
            background: transparent;
            color: {_SIDEBAR_TEXT};
            text-align: left;
            padding: 12px 16px;
            font-size: 14px;
        }}
        QPushButton:hover {{
            background: rgba(124, 58, 237, 0.12);
        }}
        QPushButton:checked {{
            border-left: 4px solid {_ACCENT_PURPLE};
            background: rgba(124, 58, 237, 0.20);
            color: #ffffff;
            font-weight: bold;
        }}
    """

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setCheckable(True)
        self.setFlat(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(46)
        self.setStyleSheet(self._STYLE_BASE)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """Outer shell: sidebar + stacked content area."""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._setup_window()
        self._build_ui()
        self._switch_to(0)   # default to Overview panel

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.setWindowTitle("CyberMon — Security Monitoring")
        self.setWindowIcon(_make_shield_icon())
        self.setMinimumSize(1200, 750)
        self.resize(1280, 780)
        # No menu bar, no toolbar — just the central widget
        self.menuBar().setVisible(False)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())
        root_layout.addWidget(self._build_content_area())

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet(f"background-color: {_SIDEBAR_BG}; border: none;")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # App title at the top of the sidebar
        title = QLabel("CyberMon")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFixedHeight(56)
        title.setStyleSheet(
            f"color: {_ACCENT_PURPLE}; font-size: 17px; font-weight: bold;"
            f" background: {_SIDEBAR_BG};"
        )
        layout.addWidget(title)

        # Divider
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: #3d3d5c;")
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        # Nav buttons (mutually exclusive via QButtonGroup)
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        self._nav_buttons: list[_SidebarButton] = []

        for idx, label in enumerate(_NAV_ITEMS):
            btn = _SidebarButton(label)
            self._btn_group.addButton(btn, idx)
            layout.addWidget(btn)
            self._nav_buttons.append(btn)
            # Capture idx in lambda default arg to avoid closure capture bug
            btn.clicked.connect(lambda checked, i=idx: self._switch_to(i))

        layout.addStretch()

        # Version stamp at bottom
        ver = QLabel("v2.0 — R4")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setFixedHeight(32)
        ver.setStyleSheet(f"color: #4a4a6a; font-size: 11px; background: {_SIDEBAR_BG};")
        layout.addWidget(ver)

        return sidebar

    def _build_content_area(self) -> QStackedWidget:
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background-color: {_CONTENT_BG};")

        # Imports are lazy (inside the method) so importing main_window at the
        # module level in tests never triggers Qt widget construction.
        from src.gui.overview_panel   import OverviewPanel
        from src.gui.violations_table import ViolationsTable
        from src.gui.trend_panel      import TrendPanel

        panels = [
            OverviewPanel(self._config,   parent=self),                           # 0 Overview
            ViolationsTable(self._config, parent=self),                           # 1 Violations
            _PlaceholderPanel("Live feed panel — available in R5", parent=self),  # 2 Live Feed
            TrendPanel(self._config,      parent=self),                           # 3 Trend
            _PlaceholderPanel("Settings panel — available in R6", parent=self),   # 4 Settings
        ]
        for panel in panels:
            self._stack.addWidget(panel)

        return self._stack

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _switch_to(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        btn = self._nav_buttons[index]
        if not btn.isChecked():
            btn.setChecked(True)
