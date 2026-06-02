"""Violations table panel.

Displays all detected violations from the database in a sortable,
filterable QTableWidget with colour-coded severity badges.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.gui.data_access import get_all_violations, get_unique_hosts

# ---------------------------------------------------------------------------
# Severity colour palette
# ---------------------------------------------------------------------------
_SEVERITY_COLOURS: dict[str, tuple[str, str]] = {
    "Low":      ("#22c55e", "#14532d"),   # (background, foreground)
    "Medium":   ("#f59e0b", "#78350f"),
    "High":     ("#ef4444", "#7f1d1d"),
    "Critical": ("#7f1d1d", "#ffffff"),
}

# Recommended action strings (short — truncated in the table)
_MAX_ACTION_LEN = 45

# Column indices
_COL_SEVERITY   = 0
_COL_SCORE      = 1
_COL_TYPE       = 2
_COL_HOST       = 3
_COL_TIMESTAMP  = 4
_COL_ACTION     = 5

_HEADERS = ["Severity", "Risk Score", "Violation Type",
            "Source Host", "Timestamp", "Recommended Action"]


class ViolationsTable(QWidget):
    """Panel showing all violations sorted by risk score descending."""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # --- Top bar: title + host filter + refresh ---
        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        title = QLabel("Violations")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #1e293b;")
        top_bar.addWidget(title)
        top_bar.addStretch()

        filter_label = QLabel("Host:")
        filter_label.setStyleSheet("color: #374151;")
        top_bar.addWidget(filter_label)

        self._host_filter = QComboBox()
        self._host_filter.setFixedWidth(200)
        self._host_filter.currentTextChanged.connect(self._on_filter_changed)
        top_bar.addWidget(self._host_filter)

        refresh_btn = QPushButton("⟳  Refresh")
        refresh_btn.setFixedWidth(100)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background: #7c3aed;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
            }
            QPushButton:hover { background: #6d28d9; }
            QPushButton:pressed { background: #5b21b6; }
        """)
        refresh_btn.clicked.connect(self.refresh)
        top_bar.addWidget(refresh_btn)

        layout.addLayout(top_bar)

        # --- Table ---
        self._table = QTableWidget()
        self._table.setColumnCount(len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)
        self._table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #e2e8f0;
                background: #ffffff;
                alternate-background-color: #f8fafc;
                gridline-color: #e2e8f0;
                font-size: 13px;
            }
            QHeaderView::section {
                background: #f1f5f9;
                color: #374151;
                font-weight: bold;
                padding: 6px;
                border: none;
                border-bottom: 2px solid #e2e8f0;
            }
            QTableWidget::item:selected {
                background: #ede9fe;
                color: #1e293b;
            }
        """)

        # Column sizing
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(_COL_SEVERITY,  QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_SCORE,      QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_TYPE,       QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_COL_HOST,       QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_TIMESTAMP,  QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_ACTION,     QHeaderView.ResizeMode.Stretch)

        self._table.itemClicked.connect(self._on_row_clicked)
        layout.addWidget(self._table)

        # --- Status bar ---
        self._status = QLabel("")
        self._status.setStyleSheet("color: #6b7280; font-size: 12px;")
        layout.addWidget(self._status)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-query the database and repopulate the filter dropdown and table."""
        self._reload_host_filter()
        self._reload_table()

    def _reload_host_filter(self) -> None:
        """Populate the host dropdown from the database."""
        current = self._host_filter.currentText()
        self._host_filter.blockSignals(True)
        self._host_filter.clear()
        self._host_filter.addItem("All Hosts")
        for host in get_unique_hosts():
            self._host_filter.addItem(host)
        # Restore previous selection if still valid
        idx = self._host_filter.findText(current)
        self._host_filter.setCurrentIndex(max(idx, 0))
        self._host_filter.blockSignals(False)

    def _reload_table(self) -> None:
        """Fetch violations (with optional host filter) and fill the table."""
        host = self._host_filter.currentText()
        host_arg = None if host == "All Hosts" else host

        # Disable sorting while populating to avoid index shuffle mid-insert
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        rows = get_all_violations(host_filter=host_arg)

        self._table.setRowCount(len(rows))
        for row_idx, v in enumerate(rows):
            self._set_row(row_idx, v)

        self._table.setSortingEnabled(True)
        # Default sort: risk score descending (col 1)
        self._table.sortItems(_COL_SCORE, Qt.SortOrder.DescendingOrder)

        count = len(rows)
        self._status.setText(
            f"{count} violation{'s' if count != 1 else ''} displayed"
            + (f"  —  filter: {host}" if host != "All Hosts" else "")
        )

    def _set_row(self, row: int, v: dict) -> None:
        """Populate a single table row from a violation dict."""
        # Severity badge
        severity = v.get("severity", "")
        bg, fg = _SEVERITY_COLOURS.get(severity, ("#e5e7eb", "#374151"))
        badge = QTableWidgetItem(severity)
        badge.setBackground(QColor(bg))
        badge.setForeground(QColor(fg))
        badge.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        badge.setData(Qt.ItemDataRole.UserRole, v.get("id"))
        self._table.setItem(row, _COL_SEVERITY, badge)

        # Risk score (right-aligned, numeric sort via UserRole)
        score_val = v.get("risk_score", 0)
        score_item = QTableWidgetItem()
        score_item.setData(Qt.ItemDataRole.DisplayRole, score_val)
        score_item.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        score_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, _COL_SCORE, score_item)

        # Violation type
        vtype_item = QTableWidgetItem(v.get("violation_type", "").replace("_", " ").title())
        vtype_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, _COL_TYPE, vtype_item)

        # Source host
        host_item = QTableWidgetItem(v.get("source_host", ""))
        host_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, _COL_HOST, host_item)

        # Timestamp — reformat from ISO to YYYY-MM-DD HH:MM:SS
        ts_raw = str(v.get("timestamp", ""))
        ts_display = ts_raw[:19].replace("T", " ") if ts_raw else ""
        ts_item = QTableWidgetItem(ts_display)
        ts_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, _COL_TIMESTAMP, ts_item)

        # Recommended action (truncated)
        action = v.get("recommended_action", "")
        if len(action) > _MAX_ACTION_LEN:
            action = action[:_MAX_ACTION_LEN - 1] + "…"
        action_item = QTableWidgetItem(action)
        action_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, _COL_ACTION, action_item)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_filter_changed(self, _text: str) -> None:
        self._reload_table()

    def _on_row_clicked(self, item: QTableWidgetItem) -> None:
        """Row click handler — detail panel placeholder for R5."""
        row = item.row()
        badge = self._table.item(row, _COL_SEVERITY)
        if badge is None:
            return
        violation_id = badge.data(Qt.ItemDataRole.UserRole)
        # Detail panel will be wired in R5.
        # For now this is a no-op (does not crash).
        _ = violation_id
