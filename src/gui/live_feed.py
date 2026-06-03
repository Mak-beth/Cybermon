"""CyberMon live feed panel.

Polls the database every 3 seconds for violations with id > last_seen_id.
New entries are prepended at the top of a scrollable feed.  A QPropertyAnimation
provides a subtle fade-in.  Maximum 100 entries kept in memory.
"""
from PyQt6.QtCore import (
    QAbstractAnimation,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.data_access import get_max_violation_id, get_new_violations_since

# ---------------------------------------------------------------------------
# Severity colours (shared palette)
# ---------------------------------------------------------------------------
_SEVERITY_COLOURS = {
    "Low":      ("#22c55e", "#14532d"),
    "Medium":   ("#f59e0b", "#78350f"),
    "High":     ("#ef4444", "#7f1d1d"),
    "Critical": ("#7f1d1d", "#ffffff"),
}

_MAX_ENTRIES   = 100
_POLL_INTERVAL = 3_000   # ms


# ---------------------------------------------------------------------------
# Individual feed entry card
# ---------------------------------------------------------------------------

class _FeedEntry(QFrame):
    """A compact one-line card: severity badge | violation type | host | time."""

    def __init__(self, violation: dict, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid #e2e8f0;"
            " border-radius: 4px; }"
        )
        self.setFixedHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(12)

        # Severity badge
        severity = violation.get("severity", "")
        bg, fg = _SEVERITY_COLOURS.get(severity, ("#e5e7eb", "#374151"))
        badge = QLabel(severity)
        badge.setFixedWidth(70)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background: {bg}; color: {fg}; font-size: 11px; font-weight: bold;"
            " border-radius: 3px; padding: 2px 4px;"
        )
        layout.addWidget(badge)

        # Violation type
        vtype = violation.get("violation_type", "").replace("_", " ").title()
        type_lbl = QLabel(vtype)
        type_lbl.setStyleSheet("color: #1e293b; font-size: 12px;")
        type_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(type_lbl, stretch=1)

        # Source host
        host_lbl = QLabel(violation.get("source_host", ""))
        host_lbl.setStyleSheet("color: #6b7280; font-size: 12px;")
        host_lbl.setFixedWidth(140)
        layout.addWidget(host_lbl)

        # Timestamp (HH:MM:SS only for compact display)
        ts_raw = str(violation.get("timestamp", ""))
        ts_display = ts_raw[11:19] if len(ts_raw) >= 19 else ts_raw[:19]
        time_lbl = QLabel(ts_display)
        time_lbl.setStyleSheet("color: #9ca3af; font-size: 11px;")
        time_lbl.setFixedWidth(60)
        layout.addWidget(time_lbl)


# ---------------------------------------------------------------------------
# Live feed panel
# ---------------------------------------------------------------------------

class LiveFeedPanel(QWidget):
    """Polls the database for new violations and prepends them to a scroll list."""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._paused = False
        self._entries: list[_FeedEntry] = []

        # Initialise watermark to current DB max so only violations that arrive
        # AFTER this panel is opened appear in the feed (live-feed semantics).
        self._last_seen_id: int = self._fetch_current_max_id()

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_INTERVAL)
        self._timer.timeout.connect(self._poll)
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
        hdr.setSpacing(10)

        title = QLabel("Live Feed")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #1e293b;")
        hdr.addWidget(title)
        hdr.addStretch()

        self._status_lbl = QLabel("Watching for new violations…")
        self._status_lbl.setStyleSheet("color: #9ca3af; font-size: 12px;")
        hdr.addWidget(self._status_lbl)

        self._pause_btn = QPushButton("⏸  Pause")
        self._pause_btn.setCheckable(True)
        self._pause_btn.setFixedWidth(90)
        self._pause_btn.setStyleSheet("""
            QPushButton {
                background: #f1f5f9; color: #374151;
                border: 1px solid #e2e8f0; border-radius: 4px;
                padding: 5px 10px; font-size: 12px;
            }
            QPushButton:checked { background: #fef3c7; color: #92400e; border-color: #f59e0b; }
            QPushButton:hover   { background: #e2e8f0; }
        """)
        self._pause_btn.clicked.connect(self._on_pause_toggled)
        hdr.addWidget(self._pause_btn)

        clear_btn = QPushButton("🗑  Clear")
        clear_btn.setFixedWidth(80)
        clear_btn.setStyleSheet("""
            QPushButton {
                background: #fee2e2; color: #991b1b;
                border: 1px solid #fca5a5; border-radius: 4px;
                padding: 5px 10px; font-size: 12px;
            }
            QPushButton:hover { background: #fecaca; }
        """)
        clear_btn.clicked.connect(self._clear)
        hdr.addWidget(clear_btn)

        root.addLayout(hdr)

        # --- Scrollable feed ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: #f8fafc;")

        self._feed_widget = QWidget()
        self._feed_widget.setStyleSheet("background: #f8fafc;")
        self._feed_layout = QVBoxLayout(self._feed_widget)
        self._feed_layout.setContentsMargins(0, 0, 0, 0)
        self._feed_layout.setSpacing(4)
        self._feed_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._feed_layout.addStretch(1)   # pushes entries to the top

        scroll.setWidget(self._feed_widget)
        root.addWidget(scroll, stretch=1)

        # --- Empty-state hint (shown until first entry arrives) ---
        self._empty_lbl = QLabel("No new violations detected yet.")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet("color: #9ca3af; font-size: 14px;")
        # Place it inside the scroll area's content widget
        self._feed_layout.insertWidget(0, self._empty_lbl)

    # ------------------------------------------------------------------
    # Polling and entry management
    # ------------------------------------------------------------------

    def _fetch_current_max_id(self) -> int:
        """Query the DB for the highest existing violation id."""
        try:
            return get_max_violation_id()
        except Exception:
            return 0

    def _poll(self) -> None:
        """Fetch violations that appeared since last poll and add them to the feed."""
        if self._paused:
            return
        try:
            new_violations = get_new_violations_since(self._last_seen_id)
        except Exception:
            return

        if not new_violations:
            return

        # Update watermark BEFORE rendering (prevents duplicates even if rendering is slow)
        self._last_seen_id = new_violations[-1]["id"]

        # Hide empty-state label on first real entry
        if self._entries == [] and self._empty_lbl.isVisible():
            self._empty_lbl.setVisible(False)

        # Prepend entries (ascending id order → each insert at 0 puts latest on top)
        for v in new_violations:
            self._prepend_entry(v)

        n = len(self._entries)
        self._status_lbl.setText(f"{n} violation{'s' if n != 1 else ''} in feed")

    def _prepend_entry(self, violation: dict) -> None:
        """Create a feed card, insert at top, animate in, enforce size cap."""
        entry = _FeedEntry(violation, parent=self._feed_widget)
        # Insert at position 0 (before the stretch at the end)
        self._feed_layout.insertWidget(0, entry)
        self._entries.insert(0, entry)
        self._animate_in(entry)

        # Enforce 100-entry cap — drop from the bottom
        while len(self._entries) > _MAX_ENTRIES:
            old = self._entries.pop()
            self._feed_layout.removeWidget(old)
            old.deleteLater()

    @staticmethod
    def _animate_in(widget: QWidget) -> None:
        """Fade the widget in from 0 → 1 opacity over 350 ms."""
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", widget)  # widget owns anim
        anim.setDuration(350)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_pause_toggled(self, checked: bool) -> None:
        self._paused = checked
        self._pause_btn.setText("▶  Resume" if checked else "⏸  Pause")

    def _clear(self) -> None:
        """Remove all displayed cards and advance watermark to current DB max."""
        for entry in self._entries:
            self._feed_layout.removeWidget(entry)
            entry.deleteLater()
        self._entries.clear()

        # Advance watermark so cleared violations don't reappear
        self._last_seen_id = self._fetch_current_max_id()

        self._empty_lbl.setVisible(True)
        self._status_lbl.setText("Feed cleared.")
