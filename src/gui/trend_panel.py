"""CyberMon trend panel.

Two-tab PyQtGraph line chart: "Today by Hour" and "Last 7 Days".
Three lines per chart: Failed Logins (purple), Unauthorized Access (red),
Off-Hours Logins (amber).
"""
import pyqtgraph as pg
from pyqtgraph import mkPen

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.gui.data_access import get_trend_by_day_week, get_trend_by_hour_today
from src.gui import theme as _theme

# Suppress pyqtgraph's "no display" warning when running headless
pg.setConfigOption("crashWarning", False)

# ---------------------------------------------------------------------------
# Colour / style constants
# ---------------------------------------------------------------------------
_BG_COLOUR     = "#f8f9fa"      # matches application content background
_GRID_COLOUR   = (220, 220, 220, 80)

_LINES = [
    ("failed_logins",       "Failed Logins",       "#7c3aed"),
    ("unauthorized_access", "Unauthorized Access",  "#ef4444"),
    ("off_hours_login",     "Off-Hours Logins",     "#f59e0b"),
]


def _make_plot(title: str = "") -> pg.PlotWidget:
    """Return a styled PlotWidget."""
    pw = pg.PlotWidget(background=_BG_COLOUR)
    pi = pw.getPlotItem()
    pi.setTitle(title, color="#374151", size="12pt")
    pi.showGrid(x=True, y=True, alpha=0.3)
    pi.getAxis("left").setLabel("Violations", color="#374151")
    pi.getAxis("left").setPen(pg.mkPen("#9ca3af"))
    pi.getAxis("bottom").setPen(pg.mkPen("#9ca3af"))
    pi.setMenuEnabled(False)
    # Ensure y-axis starts at 0
    pi.setYRange(0, 1)
    pi.enableAutoRange(axis="y", enable=True)
    return pw


# ---------------------------------------------------------------------------
# Trend panel
# ---------------------------------------------------------------------------

class TrendPanel(QWidget):
    """Shows violation trends by hour (today) and by day (last 7 days)."""

    # Auto-refresh cadence — matches the Overview / Live Feed polling pattern.
    _REFRESH_INTERVAL = 5_000   # 5 s

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._build_ui()
        self.refresh()

        # Poll so today's / this week's new violations appear without a manual
        # Refresh. Reuses the existing trend queries as-is (no window change).
        self._timer = QTimer(self)
        self._timer.setInterval(self._REFRESH_INTERVAL)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # --- Header ---
        hdr = QHBoxLayout()
        self._title_lbl = QLabel("Trend")
        self._title_lbl.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {_theme.get_active()['text_primary']};"
        )
        hdr.addWidget(self._title_lbl)
        hdr.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedWidth(100)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background: #7c3aed; color: white;
                border: none; border-radius: 4px;
                padding: 5px 10px; font-size: 13px;
            }
            QPushButton:hover   { background: #6d28d9; }
            QPushButton:pressed { background: #5b21b6; }
        """)
        refresh_btn.clicked.connect(self.refresh)
        hdr.addWidget(refresh_btn)
        root.addLayout(hdr)

        # --- Tab widget ---
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane   { border: 1px solid #e2e8f0; border-radius: 4px; }
            QTabBar::tab       { padding: 6px 18px; color: #374151; }
            QTabBar::tab:selected { background: #7c3aed; color: white; border-radius: 2px; }
        """)
        root.addWidget(self._tabs, stretch=1)

        self._tabs.addTab(self._build_today_tab(), "Today by Hour")
        self._tabs.addTab(self._build_week_tab(),  "Last 7 Days")

    def _build_today_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        self._today_plot = _make_plot("Violations Today — by Hour")
        pi = self._today_plot.getPlotItem()

        # X-axis: hours 0-23
        pi.getAxis("bottom").setLabel("Hour of Day", color="#374151")
        pi.getAxis("bottom").setTicks(
            [[(h, str(h)) for h in range(0, 24, 2)]]
        )

        # Add legend once; PlotDataItems persist so legend stays valid
        legend = pi.addLegend(
            offset=(10, 10),
            labelTextColor="#374151",
            brush=pg.mkBrush("#ffffff80"),
        )

        self._today_lines: dict[str, pg.PlotDataItem] = {}
        hours = list(range(24))
        zeros = [0] * 24
        for key, label, colour in _LINES:
            item = pi.plot(
                hours, zeros,
                pen=mkPen(colour, width=2),
                name=label,
            )
            self._today_lines[key] = item

        layout.addWidget(self._today_plot)
        return widget

    def _build_week_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        self._week_plot = _make_plot("Violations — Last 7 Days")
        pi = self._week_plot.getPlotItem()
        pi.getAxis("bottom").setLabel("Date", color="#374151")

        # X-axis tick labels are set dynamically in _update_week_chart
        self._week_x_axis = pi.getAxis("bottom")

        pi.addLegend(
            offset=(10, 10),
            labelTextColor="#374151",
            brush=pg.mkBrush("#ffffff80"),
        )

        self._week_lines: dict[str, pg.PlotDataItem] = {}
        indices = list(range(7))
        zeros = [0] * 7
        for key, label, colour in _LINES:
            item = pi.plot(
                indices, zeros,
                pen=mkPen(colour, width=2),
                name=label,
            )
            self._week_lines[key] = item

        layout.addWidget(self._week_plot)
        return widget

    # ------------------------------------------------------------------
    # Theme support
    # ------------------------------------------------------------------

    def apply_theme(self, palette: dict) -> None:
        bg = palette["content_bg"]
        text = palette["text_primary"]
        muted = palette["text_secondary"]
        bdr = palette["border"]

        self.setStyleSheet(f"background: {bg};")

        # Update title label
        self._title_lbl.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {text};"
        )

        # Tab widget
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane   {{ border: 1px solid {bdr}; border-radius: 4px; background: {bg}; }}
            QTabBar::tab       {{ padding: 6px 18px; color: {muted}; background: {palette['card_bg']}; }}
            QTabBar::tab:selected {{ background: #7c3aed; color: white; border-radius: 2px; }}
        """)

        # PyQtGraph plots — update background colour
        for plot in (self._today_plot, self._week_plot):
            plot.setBackground(bg)
            pi = plot.getPlotItem()
            pi.setTitle(pi.titleLabel.text, color=text, size="12pt")
            pi.getAxis("left").setPen(pg.mkPen(muted))
            pi.getAxis("bottom").setPen(pg.mkPen(muted))
            pi.getAxis("left").setTextPen(pg.mkPen(muted))
            pi.getAxis("bottom").setTextPen(pg.mkPen(muted))

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._update_today_chart()
        self._update_week_chart()

    def _update_today_chart(self) -> None:
        try:
            data = get_trend_by_hour_today()
        except Exception:
            data = {k: [0] * 24 for k, _, _ in _LINES}

        hours = list(range(24))
        max_val = 1
        for key, line in self._today_lines.items():
            vals = data.get(key, [0] * 24)
            line.setData(hours, vals)
            max_val = max(max_val, max(vals, default=0))

        self._today_plot.getPlotItem().setYRange(0, max_val + 1)

    def _update_week_chart(self) -> None:
        try:
            data = get_trend_by_day_week()
        except Exception:
            data = {"dates": [""] * 7, **{k: [0] * 7 for k, _, _ in _LINES}}

        dates = data.get("dates", [""] * 7)
        indices = list(range(len(dates)))

        # Update x-axis tick labels (short date: MM-DD)
        short_dates = [d[5:] if len(d) >= 7 else d for d in dates]
        self._week_x_axis.setTicks(
            [[(i, short_dates[i]) for i in range(len(short_dates))]]
        )

        max_val = 1
        for key, line in self._week_lines.items():
            vals = data.get(key, [0] * 7)
            line.setData(indices, vals)
            max_val = max(max_val, max(vals, default=0))

        self._week_plot.getPlotItem().setYRange(0, max_val + 1)
