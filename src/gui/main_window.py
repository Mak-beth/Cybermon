"""CyberMon main application window.

Outer shell: optional warning banner + sidebar navigation + QStackedWidget
content area.  Manages theme application across all panels.
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
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

from src.gui import theme as _theme

# ---------------------------------------------------------------------------
# Palette constants — sidebar stays dark in both themes
# ---------------------------------------------------------------------------
_ACCENT_PURPLE = "#7c3aed"
_CONTENT_BG    = "#f8f9fa"   # used only as fallback before theme is applied

_NAV_ITEMS = ["Overview", "Violations", "Live Feed", "Trend", "Settings"]


# ---------------------------------------------------------------------------
# Shield icon
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
    p.setBrush(QColor("#ffffff"))
    p.drawRoundedRect(11, 16, 10, 8, 2, 2)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------------
# Sidebar button
# ---------------------------------------------------------------------------

class _SidebarButton(QPushButton):
    def __init__(self, label: str, sidebar_bg: str, parent=None):
        super().__init__(label, parent)
        self._sidebar_bg = sidebar_bg
        self.setCheckable(True)
        self.setFlat(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(46)
        self._apply_style(sidebar_bg)

    def _apply_style(self, sidebar_bg: str) -> None:
        self.setStyleSheet(f"""
            QPushButton {{
                border: none;
                border-left: 4px solid transparent;
                background: transparent;
                color: #e2e8f0;
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
        """)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config

        # Initialise active theme from config before building UI
        theme_name = config.get("ui", {}).get("theme", "light")
        _theme.set_active(theme_name)

        # Apply global app-level stylesheet
        QApplication.instance().setStyleSheet(
            _theme.build_app_stylesheet(_theme.get_active())
        )

        self._setup_window()
        self._build_ui()
        self._check_warnings(config)
        self._switch_to(0)

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.setWindowTitle("CyberMon - Security Monitoring")
        self.setWindowIcon(_make_shield_icon())
        self.setMinimumSize(1200, 750)
        self.resize(1280, 780)
        self.menuBar().setVisible(False)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._warning_banner = self._build_warning_banner()
        outer.addWidget(self._warning_banner)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(0)

        self._sidebar_widget = self._build_sidebar()
        content_row.addWidget(self._sidebar_widget)
        content_row.addWidget(self._build_content_area())
        outer.addLayout(content_row)

    def _build_warning_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("warning_banner")
        banner.setStyleSheet("""
            QFrame#warning_banner {
                background: #fef3c7;
                border-bottom: 1px solid #f59e0b;
            }
        """)
        banner.setFixedHeight(38)

        row = QHBoxLayout(banner)
        row.setContentsMargins(12, 0, 8, 0)
        row.setSpacing(8)

        icon_lbl = QLabel("!")
        icon_lbl.setStyleSheet(
            "color: #d97706; font-size: 16px; font-weight: bold; background: transparent;"
        )
        icon_lbl.setFixedWidth(16)
        row.addWidget(icon_lbl)

        self._banner_text = QLabel("")
        self._banner_text.setStyleSheet(
            "color: #92400e; font-size: 13px; background: transparent;"
        )
        row.addWidget(self._banner_text, stretch=1)

        settings_link = QPushButton("Check your settings")
        settings_link.setFlat(True)
        settings_link.setStyleSheet("""
            QPushButton {
                color: #7c3aed; font-size: 13px;
                text-decoration: underline;
                border: none; background: transparent; padding: 0 4px;
            }
            QPushButton:hover { color: #6d28d9; }
        """)
        settings_link.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_link.clicked.connect(lambda: self._switch_to(4))
        row.addWidget(settings_link)

        dismiss_btn = QPushButton("x")
        dismiss_btn.setFlat(True)
        dismiss_btn.setFixedWidth(24)
        dismiss_btn.setFixedHeight(24)
        dismiss_btn.setStyleSheet(
            "color: #92400e; border: none; background: transparent; font-size: 14px;"
        )
        dismiss_btn.clicked.connect(lambda: banner.setVisible(False))
        row.addWidget(dismiss_btn)

        banner.setVisible(False)
        return banner

    def _build_sidebar(self) -> QFrame:
        sidebar_bg = _theme.get_active()["sidebar_bg"]
        sidebar = QFrame()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet(f"background-color: {sidebar_bg}; border: none;")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel("CyberMon")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFixedHeight(56)
        title.setStyleSheet(
            f"color: {_ACCENT_PURPLE}; font-size: 17px; font-weight: bold;"
            f" background: {sidebar_bg};"
        )
        layout.addWidget(title)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: #3d3d5c;")
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        self._nav_buttons: list[_SidebarButton] = []

        for idx, label in enumerate(_NAV_ITEMS):
            btn = _SidebarButton(label, sidebar_bg)
            self._btn_group.addButton(btn, idx)
            layout.addWidget(btn)
            self._nav_buttons.append(btn)
            btn.clicked.connect(lambda checked, i=idx: self._switch_to(i))

        if self._config.get("mode") == "network":
            layout.addSpacing(8)
            agent_indicator = QLabel("  No agents connected")
            agent_indicator.setStyleSheet(
                f"color: #ef4444; font-size: 11px; padding: 4px 12px;"
                f" background: {sidebar_bg};"
            )
            agent_indicator.setToolTip("No agents connected. Check agent configuration.")
            layout.addWidget(agent_indicator)

        layout.addStretch()

        self._ver_lbl = QLabel("v2.0")
        self._ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ver_lbl.setFixedHeight(32)
        self._ver_lbl.setStyleSheet(
            f"color: #4a4a6a; font-size: 11px; background: {sidebar_bg};"
        )
        layout.addWidget(self._ver_lbl)

        return sidebar

    def _build_content_area(self) -> QStackedWidget:
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(
            f"background-color: {_theme.get_active()['content_bg']};"
        )

        from src.gui.overview_panel   import OverviewPanel
        from src.gui.violations_table import ViolationsTable
        from src.gui.live_feed        import LiveFeedPanel
        from src.gui.trend_panel      import TrendPanel
        from src.gui.settings_panel   import SettingsPanel

        self._panels = [
            OverviewPanel(self._config,   parent=self),    # 0
            ViolationsTable(self._config, parent=self),    # 1
            LiveFeedPanel(self._config,   parent=self),    # 2
            TrendPanel(self._config,      parent=self),    # 3
            SettingsPanel(self._config,   parent=self),    # 4
        ]
        for panel in self._panels:
            self._stack.addWidget(panel)

        # Wire theme-change signal from settings panel
        self._panels[4].theme_changed.connect(self.apply_theme)

        return self._stack

    # ------------------------------------------------------------------
    # Theme application
    # ------------------------------------------------------------------

    def apply_theme(self, theme_name: str) -> None:
        """Apply theme to the app stylesheet and all panels immediately."""
        _theme.set_active(theme_name)
        palette = _theme.get_active()

        # Global fallback stylesheet
        QApplication.instance().setStyleSheet(
            _theme.build_app_stylesheet(palette)
        )

        # Content area background
        self._stack.setStyleSheet(
            f"background-color: {palette['content_bg']};"
        )

        # Per-panel stylesheets
        for panel in self._panels:
            if hasattr(panel, "apply_theme"):
                panel.apply_theme(palette)

    # ------------------------------------------------------------------
    # Warnings / error notifications
    # ------------------------------------------------------------------

    def _check_warnings(self, config: dict) -> None:
        missing = []
        for key in ("auth_log_path", "web_log_path"):
            path = config.get(key)
            if path and not os.path.exists(path):
                missing.append(path)
        if missing:
            self._banner_text.setText(
                "Log file not found at " + ", ".join(missing) + "."
            )
            self._warning_banner.setVisible(True)

    def show_error_banner(self, msg: str) -> None:
        self._banner_text.setText(f"Error: {msg}  See cybermon.log for details.")
        self._warning_banner.setVisible(True)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _switch_to(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        btn = self._nav_buttons[index]
        if not btn.isChecked():
            btn.setChecked(True)
