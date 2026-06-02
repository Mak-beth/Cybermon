"""CyberMon overview panel.

Shows four metric cards (total, critical, high, med+low), a per-type
breakdown with progress bars, and a doughnut chart for severity distribution.
Auto-refreshes every 30 seconds via QTimer.  Host filter dropdown mirrors the
violations table filter.
"""
from datetime import datetime

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.data_access import get_summary_counts, get_unique_hosts

# ---------------------------------------------------------------------------
# Metric card
# ---------------------------------------------------------------------------

class _MetricCard(QFrame):
    """A small card showing a single integer metric with a coloured accent."""

    def __init__(self, title: str, accent: str, parent=None):
        super().__init__(parent)
        self._accent = accent
        self._build(title)

    def _build(self, title: str) -> None:
        self.setStyleSheet(f"""
            QFrame {{
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-left: 5px solid {self._accent};
                border-radius: 6px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        self._value_lbl = QLabel("0")
        self._value_lbl.setStyleSheet(
            f"color: {self._accent}; font-size: 30px; font-weight: bold; border: none;"
        )
        layout.addWidget(self._value_lbl)

        title_lbl = QLabel(title)
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet("color: #6b7280; font-size: 12px; border: none;")
        layout.addWidget(title_lbl)

    def set_value(self, value: int) -> None:
        self._value_lbl.setText(str(value))


# ---------------------------------------------------------------------------
# Doughnut chart (custom QPainter widget)
# ---------------------------------------------------------------------------

class _DoughnutChart(QWidget):
    """Draws a doughnut chart from severity counts using QPainter arcs."""

    # Render order: most severe first so colours are visually dominant
    _ORDER = ["Critical", "High", "Medium", "Low"]
    _COLOURS = {
        "Critical": QColor("#7f1d1d"),
        "High":     QColor("#ef4444"),
        "Medium":   QColor("#f59e0b"),
        "Low":      QColor("#22c55e"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: dict[str, int] = {k: 0 for k in self._ORDER}
        self.setMinimumSize(160, 160)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

    def set_data(self, data: dict) -> None:
        self._data = data
        self.update()   # schedule repaint

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        total = sum(self._data.get(k, 0) for k in self._ORDER)
        rect = self.rect()
        size = min(rect.width(), rect.height()) - 16
        cx = rect.width() // 2
        cy = rect.height() // 2

        ring_w = max(int(size * 0.22), 18)
        half_rw = ring_w / 2
        # Arc is drawn centred on the pen line, so inset by half pen width
        arc_rect = QRectF(
            cx - size / 2 + half_rw,
            cy - size / 2 + half_rw,
            size - ring_w,
            size - ring_w,
        )

        pen = QPen()
        pen.setWidth(ring_w)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if total == 0:
            pen.setColor(QColor("#e2e8f0"))
            painter.setPen(pen)
            painter.drawArc(arc_rect, 0, 360 * 16)
            painter.setPen(QColor("#9ca3af"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No data")
            painter.end()
            return

        # Draw segments starting at 12 o'clock, going clockwise
        start = 90 * 16
        for severity in self._ORDER:
            count = self._data.get(severity, 0)
            if count == 0:
                continue
            span = int(round(count / total * 360 * 16))
            pen.setColor(self._COLOURS[severity])
            painter.setPen(pen)
            painter.drawArc(arc_rect, start, -span)   # negative = clockwise
            start -= span

        # Centre: total count in bold
        pen2 = QPen(QColor("#1e293b"))
        painter.setPen(pen2)
        font = painter.font()
        font.setPixelSize(max(int(size * 0.17), 14))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(total))
        painter.end()


# ---------------------------------------------------------------------------
# Overview panel
# ---------------------------------------------------------------------------

class OverviewPanel(QWidget):
    """Main overview panel: metric cards + breakdown bars + doughnut chart."""

    _BAR_DEFS = [
        ("failed_logins",       "Repeated Failed Logins",  "#7c3aed"),
        ("unauthorized_access", "Unauthorized Access",      "#ef4444"),
        ("off_hours_login",     "Off-Hours Logins",         "#f59e0b"),
    ]

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._build_ui()

        # 30-second auto-refresh timer
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

        # Initial load
        self._reload_host_filter()
        self.refresh()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(12)

        root.addLayout(self._build_header())
        root.addLayout(self._build_middle(), stretch=1)
        root.addLayout(self._build_footer())

    def _build_header(self) -> QHBoxLayout:
        hdr = QHBoxLayout()
        hdr.setSpacing(10)

        title = QLabel("Overview")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #1e293b;")
        hdr.addWidget(title)
        hdr.addStretch()

        hdr.addWidget(QLabel("Host:"))

        self._host_filter = QComboBox()
        self._host_filter.setFixedWidth(200)
        # Connect after widget exists — signals blocked during _reload_host_filter
        self._host_filter.currentTextChanged.connect(self.refresh)
        hdr.addWidget(self._host_filter)

        refresh_btn = QPushButton("⟳  Refresh")
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

        return hdr

    def _build_middle(self) -> QHBoxLayout:
        mid = QHBoxLayout()
        mid.setSpacing(16)

        # Left: cards + breakdown
        left = QVBoxLayout()
        left.setSpacing(12)
        left.addLayout(self._build_metric_cards())
        left.addWidget(self._build_breakdown_frame())
        left.addStretch()
        mid.addLayout(left, stretch=2)

        # Right: doughnut
        right_frame = QFrame()
        right_frame.setStyleSheet(
            "background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px;"
        )
        rf_layout = QVBoxLayout(right_frame)
        rf_layout.setContentsMargins(8, 8, 8, 8)
        rf_layout.setSpacing(4)

        chart_lbl = QLabel("Severity Distribution")
        chart_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chart_lbl.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #374151; border: none;"
        )
        rf_layout.addWidget(chart_lbl)

        self._doughnut = _DoughnutChart()
        rf_layout.addWidget(self._doughnut, stretch=1)

        # Legend below chart
        rf_layout.addLayout(self._build_legend())
        mid.addWidget(right_frame, stretch=1)

        return mid

    def _build_metric_cards(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        self._card_total    = _MetricCard("Total Violations", "#3b82f6")
        self._card_critical = _MetricCard("Critical",          "#7f1d1d")
        self._card_high     = _MetricCard("High",              "#ef4444")
        self._card_medlow   = _MetricCard("Medium + Low",      "#f59e0b")

        for card in (self._card_total, self._card_critical,
                     self._card_high, self._card_medlow):
            row.addWidget(card)
        return row

    def _build_breakdown_frame(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        section_title = QLabel("Violation Breakdown")
        section_title.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #374151; border: none;"
        )
        layout.addWidget(section_title)

        self._bars: dict[str, tuple[QLabel, QProgressBar]] = {}
        for key, label_text, color in self._BAR_DEFS:
            row = QHBoxLayout()
            row.setSpacing(8)

            lbl = QLabel(label_text)
            lbl.setFixedWidth(175)
            lbl.setStyleSheet("color: #374151; font-size: 12px; border: none;")
            row.addWidget(lbl)

            count_lbl = QLabel("0")
            count_lbl.setFixedWidth(32)
            count_lbl.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            count_lbl.setStyleSheet(
                "color: #1e293b; font-weight: bold; font-size: 13px; border: none;"
            )
            row.addWidget(count_lbl)

            bar = QProgressBar()
            bar.setMaximum(1)
            bar.setValue(0)
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            bar.setStyleSheet(f"""
                QProgressBar {{
                    background: #e2e8f0;
                    border-radius: 5px;
                    border: none;
                }}
                QProgressBar::chunk {{
                    background: {color};
                    border-radius: 5px;
                }}
            """)
            row.addWidget(bar)
            layout.addLayout(row)
            self._bars[key] = (count_lbl, bar)

        return frame

    def _build_legend(self) -> QHBoxLayout:
        legend = QHBoxLayout()
        legend.setSpacing(8)
        legend.addStretch()
        _entries = [
            ("Critical", "#7f1d1d"),
            ("High",     "#ef4444"),
            ("Medium",   "#f59e0b"),
            ("Low",      "#22c55e"),
        ]
        for label, color in _entries:
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; border: none; font-size: 14px;")
            legend.addWidget(dot)
            txt = QLabel(label)
            txt.setStyleSheet("color: #374151; font-size: 11px; border: none;")
            legend.addWidget(txt)
        legend.addStretch()
        return legend

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.addStretch()
        self._last_updated = QLabel("")
        self._last_updated.setStyleSheet("color: #9ca3af; font-size: 12px;")
        footer.addWidget(self._last_updated)
        return footer

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _reload_host_filter(self) -> None:
        """Repopulate the host dropdown; restore previous selection."""
        current = self._host_filter.currentText()
        self._host_filter.blockSignals(True)
        self._host_filter.clear()
        self._host_filter.addItem("All Hosts")
        for host in get_unique_hosts():
            self._host_filter.addItem(host)
        idx = self._host_filter.findText(current)
        self._host_filter.setCurrentIndex(max(idx, 0))
        self._host_filter.blockSignals(False)

    def refresh(self) -> None:
        """Re-query the database and update all widgets."""
        # Reload host dropdown first (catches newly-appearing hosts)
        self._reload_host_filter()

        host = self._host_filter.currentText()
        host_arg = None if host == "All Hosts" else host

        try:
            summary = get_summary_counts(host_filter=host_arg)
        except Exception:
            summary = {
                "total": 0,
                "by_type": {},
                "by_severity": {},
            }

        total      = summary["total"]
        by_severity = summary["by_severity"]
        by_type     = summary["by_type"]

        # Metric cards
        self._card_total.set_value(total)
        self._card_critical.set_value(by_severity.get("Critical", 0))
        self._card_high.set_value(by_severity.get("High", 0))
        med_low = by_severity.get("Medium", 0) + by_severity.get("Low", 0)
        self._card_medlow.set_value(med_low)

        # Breakdown bars
        bar_max = max(total, 1)
        for key, (count_lbl, bar) in self._bars.items():
            count = by_type.get(key, 0)
            count_lbl.setText(str(count))
            bar.setMaximum(bar_max)
            bar.setValue(count)

        # Doughnut chart
        self._doughnut.set_data(by_severity)

        # Timestamp
        self._last_updated.setText(
            f"Last updated: {datetime.now().strftime('%H:%M:%S')}"
        )
