"""CyberMon main application window.

Outer shell: optional warning banner + sidebar navigation + QStackedWidget
content area.  Manages theme application across all panels.
"""
import logging
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

logger = logging.getLogger(__name__)

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
    """Sidebar nav item. Styled by object name in the app stylesheet."""

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setObjectName("navButton")
        self.setCheckable(True)
        self.setFlat(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(46)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config

        # Theme is a UI preference: read it from QSettings, not config.yaml
        # (which holds detection rules). Applied before the UI is built.
        _theme.set_active("dark" if _theme.load_saved_theme() else "light")
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
        banner.setFixedHeight(38)

        row = QHBoxLayout(banner)
        row.setContentsMargins(12, 0, 8, 0)
        row.setSpacing(8)

        icon_lbl = QLabel("!")
        icon_lbl.setObjectName("bannerIcon")
        icon_lbl.setFixedWidth(16)
        row.addWidget(icon_lbl)

        self._banner_text = QLabel("")
        row.addWidget(self._banner_text, stretch=1)

        settings_link = QPushButton("Check your settings")
        settings_link.setFlat(True)
        settings_link.setObjectName("bannerLink")
        settings_link.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_link.clicked.connect(lambda: self._switch_to(4))
        row.addWidget(settings_link)

        dismiss_btn = QPushButton("x")
        dismiss_btn.setFlat(True)
        dismiss_btn.setFixedWidth(24)
        dismiss_btn.setFixedHeight(24)
        dismiss_btn.setObjectName("bannerDismiss")
        dismiss_btn.clicked.connect(lambda: banner.setVisible(False))
        row.addWidget(dismiss_btn)

        banner.setVisible(False)
        return banner

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel("CyberMon")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFixedHeight(56)
        title.setObjectName("sidebarTitle")
        layout.addWidget(title)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setObjectName("sidebarDivider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        self._nav_buttons: list[_SidebarButton] = []

        for idx, label in enumerate(_NAV_ITEMS):
            btn = _SidebarButton(label)
            self._btn_group.addButton(btn, idx)
            layout.addWidget(btn)
            self._nav_buttons.append(btn)
            btn.clicked.connect(lambda checked, i=idx: self._switch_to(i))

        if self._config.get("mode") == "network":
            layout.addSpacing(8)
            agent_indicator = QLabel("  No agents connected")
            agent_indicator.setObjectName("agentIndicator")
            agent_indicator.setToolTip("No agents connected. Check agent configuration.")
            layout.addWidget(agent_indicator)

        layout.addStretch()

        self._ver_lbl = QLabel("v2.0")
        self._ver_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ver_lbl.setFixedHeight(32)
        self._ver_lbl.setObjectName("sidebarVersion")
        layout.addWidget(self._ver_lbl)

        return sidebar

    def _build_content_area(self) -> QStackedWidget:
        self._stack = QStackedWidget()

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
        # Re-scored scores are already in the DB; pull them into the views.
        self._panels[4].rescored.connect(self.refresh_data_panels)

        return self._stack

    def refresh_data_panels(self) -> None:
        """Reload Overview, Violations and Trend from the database.

        Called after a re-score so updated scores appear without waiting for
        the panels' own poll timers. Live Feed is intentionally left alone: it
        is a watermark-based stream of NEW violations, and a re-score creates
        none — it only rewrites the scores of existing ones.
        """
        for index in (0, 1, 3):          # Overview, Violations, Trend
            panel = self._panels[index]
            try:
                panel.refresh()
            except Exception:
                logger.exception(
                    "main_window: could not refresh panel %d after re-score", index
                )

    # ------------------------------------------------------------------
    # Theme application
    # ------------------------------------------------------------------

    def apply_theme(self, theme_name: str) -> None:
        """Switch theme app-wide. Instant hard swap, no animation.

        Delegates to theme.apply_theme(), the single source of truth: it sets
        the app-wide stylesheet, re-themes registered charts, and persists the
        choice to QSettings.
        """
        _theme.apply_theme(theme_name == "dark")

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
