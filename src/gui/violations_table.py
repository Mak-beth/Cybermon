"""Violations table panel.

Displays all detected violations from the database in a sortable,
filterable QTableWidget with colour-coded severity badges.
Includes CSV export (respects current host filter) and a friendly
empty state when the database contains no violations.
"""
import csv
from datetime import date

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.gui.data_access import (
    get_all_violations,
    get_unique_hosts,
    get_violations_for_export,
)
from src.gui import theme as _theme

# ---------------------------------------------------------------------------
# Severity colour palette
# ---------------------------------------------------------------------------
_SEVERITY_COLOURS: dict[str, tuple[str, str]] = {
    "Low":      ("#22c55e", "#14532d"),   # (background, foreground)
    "Medium":   ("#f59e0b", "#78350f"),
    "High":     ("#ef4444", "#7f1d1d"),
    "Critical": ("#7f1d1d", "#ffffff"),
}

_MAX_ACTION_LEN = 45

# Column indices
_COL_SEVERITY  = 0
_COL_SCORE     = 1
_COL_TYPE      = 2
_COL_HOST      = 3
_COL_TIMESTAMP = 4
_COL_ACTION    = 5

_HEADERS = ["Severity", "Risk Score", "Violation Type",
            "Source Host", "Timestamp", "Recommended Action"]

# CSV columns — exact order required by the spec
_CSV_COLUMNS = [
    "timestamp", "violation_type", "source_host",
    "likelihood", "impact", "risk_score", "severity",
    "recommended_action", "log_excerpt",
]


class ViolationsTable(QWidget):
    """Panel showing all violations sorted by risk score descending."""

    # Auto-refresh cadence — matches the Overview / Live Feed polling pattern.
    _REFRESH_INTERVAL = 5_000   # 5 s

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        # Default sort is newest-first; preserved across auto-refreshes and
        # updated whenever the user clicks a column header.
        self._sort_col = _COL_TIMESTAMP
        self._sort_order = Qt.SortOrder.DescendingOrder
        self._reloading = False   # guard: ignore programmatic sort signals
        self._build_ui()
        self.refresh()

        # Poll the database so new violations appear without a manual Refresh.
        self._timer = QTimer(self)
        self._timer.setInterval(self._REFRESH_INTERVAL)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # --- Top bar: title + host filter + export + refresh ---
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

        export_btn = QPushButton("Export CSV")
        export_btn.setFixedWidth(110)
        export_btn.setStyleSheet("""
            QPushButton {
                background: #f1f5f9;
                color: #374151;
                border: 1px solid #e2e8f0;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
            }
            QPushButton:hover  { background: #e2e8f0; }
            QPushButton:pressed { background: #cbd5e1; }
        """)
        export_btn.clicked.connect(self._export_csv)
        top_bar.addWidget(export_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedWidth(90)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background: #7c3aed;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
            }
            QPushButton:hover   { background: #6d28d9; }
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

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(_COL_SEVERITY,  QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_SCORE,     QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_TYPE,      QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_COL_HOST,      QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_TIMESTAMP, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(_COL_ACTION,    QHeaderView.ResizeMode.Stretch)

        self._table.itemClicked.connect(self._on_row_clicked)
        self._table.horizontalHeader().sortIndicatorChanged.connect(self._on_sort_changed)

        # --- Empty state (shown when database has no violations) ---
        _empty = QWidget()
        _ev = QVBoxLayout(_empty)
        _ev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _empty_lbl = QLabel(
            "No violations detected yet.\nCyberMon is monitoring your logs."
        )
        _empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _empty_lbl.setStyleSheet("color: #6b7280; font-size: 15px;")
        _ev.addWidget(_empty_lbl)

        # Stack: index 0 = table, index 1 = empty state
        self._content_stack = QStackedWidget()
        self._content_stack.addWidget(self._table)
        self._content_stack.addWidget(_empty)
        layout.addWidget(self._content_stack)

        # --- Status bar ---
        self._status = QLabel("")
        self._status.setStyleSheet("color: #6b7280; font-size: 12px;")
        layout.addWidget(self._status)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-query the database and repopulate filter dropdown and table."""
        self._reload_host_filter()
        self._reload_table()

    def _reload_host_filter(self) -> None:
        current = self._host_filter.currentText()
        self._host_filter.blockSignals(True)
        self._host_filter.clear()
        self._host_filter.addItem("All Hosts")
        for host in get_unique_hosts():
            self._host_filter.addItem(host)
        idx = self._host_filter.findText(current)
        self._host_filter.setCurrentIndex(max(idx, 0))
        self._host_filter.blockSignals(False)

    def _reload_table(self) -> None:
        host = self._host_filter.currentText()
        host_arg = None if host == "All Hosts" else host

        self._reloading = True
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        rows = get_all_violations(host_filter=host_arg)

        if rows:
            self._content_stack.setCurrentIndex(0)
            self._table.setRowCount(len(rows))
            for row_idx, v in enumerate(rows):
                self._set_row(row_idx, v)
            self._table.setSortingEnabled(True)
            # Reapply the current sort (default: Timestamp DESC, or whatever
            # column the user last clicked) so auto-refresh doesn't disturb it.
            self._table.sortItems(self._sort_col, self._sort_order)
            count = len(rows)
            self._status.setText(
                f"{count} violation{'s' if count != 1 else ''} displayed"
                + (f"  —  filter: {host}" if host != "All Hosts" else "")
            )
        else:
            self._content_stack.setCurrentIndex(1)
            self._status.setText("No violations in database.")

        self._reloading = False

    def _on_sort_changed(self, section: int, order: Qt.SortOrder) -> None:
        """Record a user-initiated column sort so it survives auto-refresh.

        Ignored while _reload_table is repopulating (that re-sort is our own).
        """
        if self._reloading:
            return
        self._sort_col = section
        self._sort_order = order

    def _set_row(self, row: int, v: dict) -> None:
        severity = v.get("severity", "")
        bg, fg = _SEVERITY_COLOURS.get(severity, ("#e5e7eb", "#374151"))
        badge = QTableWidgetItem(severity)
        badge.setBackground(QColor(bg))
        badge.setForeground(QColor(fg))
        badge.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        badge.setData(Qt.ItemDataRole.UserRole, v.get("id"))
        self._table.setItem(row, _COL_SEVERITY, badge)

        _CELL_FG = QColor(_theme.get_active()["table_text"])

        score_val = v.get("risk_score", 0)
        score_item = QTableWidgetItem()
        score_item.setData(Qt.ItemDataRole.DisplayRole, score_val)
        score_item.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        score_item.setForeground(_CELL_FG)
        score_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, _COL_SCORE, score_item)

        vtype_item = QTableWidgetItem(
            v.get("violation_type", "").replace("_", " ").title()
        )
        vtype_item.setForeground(_CELL_FG)
        vtype_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, _COL_TYPE, vtype_item)

        host_item = QTableWidgetItem(v.get("source_host", ""))
        host_item.setForeground(_CELL_FG)
        host_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, _COL_HOST, host_item)

        ts_raw = str(v.get("timestamp", ""))
        ts_display = ts_raw[:19].replace("T", " ") if ts_raw else ""
        ts_item = QTableWidgetItem(ts_display)
        ts_item.setForeground(_CELL_FG)
        ts_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, _COL_TIMESTAMP, ts_item)

        action = v.get("recommended_action", "")
        if len(action) > _MAX_ACTION_LEN:
            action = action[:_MAX_ACTION_LEN - 1] + "…"
        action_item = QTableWidgetItem(action)
        action_item.setForeground(_CELL_FG)
        action_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
        self._table.setItem(row, _COL_ACTION, action_item)

    # ------------------------------------------------------------------
    # Theme support
    # ------------------------------------------------------------------

    def apply_theme(self, palette: dict) -> None:
        """Reapply all stylesheets and reload rows with updated cell colours."""
        self.setStyleSheet(f"background: {palette['content_bg']}; color: {palette['text_primary']};")
        self._table.setStyleSheet(f"""
            QTableWidget {{
                border: 1px solid {palette['border']};
                background: {palette['card_bg']};
                alternate-background-color: {palette['table_alt']};
                gridline-color: {palette['border']};
                font-size: 13px;
                color: {palette['table_text']};
            }}
            QHeaderView::section {{
                background: {palette['card_bg']};
                color: {palette['text_primary']};
                font-weight: bold;
                padding: 6px;
                border: none;
                border-bottom: 2px solid {palette['border']};
            }}
            QTableWidget::item:selected {{
                background: {palette['table_selected']};
                color: {palette['text_primary']};
            }}
        """)
        self._status.setStyleSheet(f"color: {palette['text_secondary']}; font-size: 12px;")
        self._reload_table()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_filter_changed(self, _text: str) -> None:
        self._reload_table()

    def _on_row_clicked(self, item: QTableWidgetItem) -> None:
        row = item.row()
        badge = self._table.item(row, _COL_SEVERITY)
        if badge is None:
            return
        violation_id = badge.data(Qt.ItemDataRole.UserRole)
        if violation_id is None:
            return
        from src.gui.detail_panel import DetailPanel
        panel = DetailPanel(violation_id, parent=self)
        panel.exec()

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    def _export_csv(self) -> None:
        """Export currently visible (filtered) violations to a CSV file."""
        host = self._host_filter.currentText()
        host_arg = None if host == "All Hosts" else host

        default_name = f"cybermon_violations_{date.today().isoformat()}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Violations to CSV",
            default_name,
            "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return  # user cancelled

        rows = get_violations_for_export(host_filter=host_arg)

        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(
                    fh, fieldnames=_CSV_COLUMNS, extrasaction="ignore"
                )
                writer.writeheader()
                writer.writerows(rows)
            self._status.setText(
                f"Exported {len(rows)} violation(s) to {path}"
            )
        except OSError as exc:
            self._status.setText(f"Export failed: {exc}")
