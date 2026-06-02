"""CyberMon violation detail panel.

Opens as a modal QDialog when a row is clicked in the violations table.
Shows the full violation record including score breakdown, log excerpt,
and recommended action.  Provides a clipboard export button.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.gui.data_access import RECOMMENDED_ACTIONS, get_violation_by_id

# ---------------------------------------------------------------------------
# Severity colours (same palette as violations table)
# ---------------------------------------------------------------------------
_SEVERITY_COLOURS = {
    "Low":      ("#22c55e", "#14532d"),
    "Medium":   ("#f59e0b", "#78350f"),
    "High":     ("#ef4444", "#7f1d1d"),
    "Critical": ("#7f1d1d", "#ffffff"),
}

# ---------------------------------------------------------------------------
# Violation type plain-English descriptions
# ---------------------------------------------------------------------------
_TYPE_DESCRIPTIONS = {
    "failed_logins":       "Multiple failed login attempts from the same source within a short time window.",
    "unauthorized_access": "Access attempt to a restricted resource that returned a 401 or 403 response.",
    "off_hours_login":     "Successful login detected outside of configured business hours.",
}

# Maximum risk score in the scoring model
_MAX_RISK_SCORE = 25


def _label(text: str, bold: bool = False, size: int = 13,
           colour: str = "#374151") -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {colour}; font-size: {size}px;"
        + (" font-weight: bold;" if bold else "")
    )
    lbl.setWordWrap(True)
    return lbl


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: #e2e8f0;")
    return line


class DetailPanel(QDialog):
    """Modal dialog showing the full detail for one violation."""

    def __init__(self, violation_id: int, parent=None):
        super().__init__(parent)
        self._violation_id = violation_id
        self._v = get_violation_by_id(violation_id)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("Violation Detail")
        self.setMinimumWidth(560)
        self.setMaximumWidth(740)
        self.setModal(True)
        self.setStyleSheet("background: #ffffff;")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Header bar with severity badge and close button ---
        root.addWidget(self._build_header())

        # --- Scrollable body ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: #ffffff;")

        body_widget = QWidget()
        body_widget.setStyleSheet("background: #ffffff;")
        body = QVBoxLayout(body_widget)
        body.setContentsMargins(24, 16, 24, 16)
        body.setSpacing(14)

        body.addLayout(self._build_score_section())
        body.addWidget(_divider())
        body.addLayout(self._build_info_section())
        body.addWidget(_divider())
        body.addLayout(self._build_log_section())
        body.addWidget(_divider())
        body.addLayout(self._build_action_section())
        body.addStretch()

        scroll.setWidget(body_widget)
        root.addWidget(scroll, stretch=1)

        # --- Footer: export button ---
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        v = self._v
        severity = v.get("severity", "")
        bg, fg = _SEVERITY_COLOURS.get(severity, ("#e5e7eb", "#374151"))

        header = QWidget()
        header.setStyleSheet(f"background: {bg};")
        header.setFixedHeight(64)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 16, 0)

        badge = QLabel(severity.upper())
        badge.setStyleSheet(
            f"color: {fg}; font-size: 18px; font-weight: bold; background: transparent;"
        )
        layout.addWidget(badge)

        vtype = v.get("violation_type", "").replace("_", " ").title()
        type_lbl = QLabel(vtype)
        type_lbl.setStyleSheet(
            f"color: {fg}; font-size: 14px; background: transparent; opacity: 0.85;"
        )
        layout.addWidget(type_lbl, stretch=1)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(32, 32)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {fg};
                border: none;
                font-size: 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: rgba(0,0,0,0.15); border-radius: 4px; }}
        """)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        return header

    def _build_score_section(self) -> QVBoxLayout:
        v = self._v
        layout = QVBoxLayout()
        layout.setSpacing(6)

        score      = v.get("risk_score", 0)
        likelihood = v.get("likelihood", 0)
        impact     = v.get("impact", 0)

        layout.addWidget(_label(
            f"Score: {score} / {_MAX_RISK_SCORE}",
            bold=True, size=20, colour="#1e293b",
        ))
        layout.addWidget(_label(
            f"Breakdown:  Likelihood {likelihood}  ×  Impact {impact}  =  {score}",
            size=13, colour="#6b7280",
        ))
        return layout

    def _build_info_section(self) -> QVBoxLayout:
        v = self._v
        layout = QVBoxLayout()
        layout.setSpacing(6)

        layout.addWidget(_label("Details", bold=True, size=13, colour="#374151"))

        vtype = v.get("violation_type", "")
        description = _TYPE_DESCRIPTIONS.get(vtype, "")
        if description:
            layout.addWidget(_label(description, size=13, colour="#6b7280"))

        for field_label, value in [
            ("Source Host", v.get("source_host", "—")),
            ("Source IP",   v.get("source_ip")   or "—"),
            ("Username",    v.get("username")     or "—"),
            ("Resource",    v.get("resource")     or "—"),
            ("Timestamp",   str(v.get("timestamp", ""))[:19].replace("T", " ")),
        ]:
            row = QHBoxLayout()
            row.addWidget(_label(f"{field_label}:", bold=True, size=12, colour="#374151"))
            row.addWidget(_label(str(value), size=12, colour="#4b5563"))
            row.addStretch()
            layout.addLayout(row)

        return layout

    def _build_log_section(self) -> QVBoxLayout:
        v = self._v
        layout = QVBoxLayout()
        layout.setSpacing(6)

        layout.addWidget(_label("Log Excerpt", bold=True, size=13, colour="#374151"))

        raw = v.get("raw_log")
        if raw:
            log_box = QTextEdit()
            log_box.setReadOnly(True)
            log_box.setPlainText(raw)
            log_box.setFixedHeight(64)
            log_box.setFont(QFont("Consolas, Courier New, monospace", 11))
            log_box.setStyleSheet(
                "background: #f1f5f9; border: 1px solid #e2e8f0; "
                "border-radius: 4px; color: #1e293b; padding: 4px;"
            )
            layout.addWidget(log_box)
        else:
            layout.addWidget(_label(
                "Not available — triggering event not recorded.",
                size=12, colour="#9ca3af",
            ))

        return layout

    def _build_action_section(self) -> QVBoxLayout:
        v = self._v
        layout = QVBoxLayout()
        layout.setSpacing(6)

        layout.addWidget(_label("Recommended Action", bold=True, size=13, colour="#374151"))

        action = v.get("recommended_action") or RECOMMENDED_ACTIONS.get(
            v.get("severity", ""), "No recommendation available."
        )
        action_lbl = _label(action, size=13, colour="#1e293b")
        action_lbl.setStyleSheet(
            "color: #1e293b; font-size: 13px;"
            " background: #eff6ff; border-left: 4px solid #3b82f6;"
            " padding: 10px 12px; border-radius: 0 4px 4px 0;"
        )
        layout.addWidget(action_lbl)

        return layout

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setStyleSheet(
            "background: #f8fafc; border-top: 1px solid #e2e8f0;"
        )
        footer.setFixedHeight(52)

        layout = QHBoxLayout(footer)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.addStretch()

        export_btn = QPushButton("📋  Export to Clipboard")
        export_btn.setStyleSheet("""
            QPushButton {
                background: #7c3aed; color: white;
                border: none; border-radius: 4px;
                padding: 8px 18px; font-size: 13px;
            }
            QPushButton:hover   { background: #6d28d9; }
            QPushButton:pressed { background: #5b21b6; }
        """)
        export_btn.clicked.connect(self._export_to_clipboard)
        layout.addWidget(export_btn)

        return footer

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export_to_clipboard(self) -> None:
        v = self._v
        ts = str(v.get("timestamp", ""))[:19].replace("T", " ")
        text = (
            "CyberMon Violation Report\n"
            "=" * 42 + "\n"
            f"Type:        {v.get('violation_type', '').replace('_', ' ').title()}\n"
            f"Severity:    {v.get('severity', '')}\n"
            f"Risk Score:  {v.get('risk_score', '')} / {_MAX_RISK_SCORE}  "
            f"(Likelihood {v.get('likelihood', '')} × Impact {v.get('impact', '')})\n"
            f"Source Host: {v.get('source_host', '')}\n"
            f"Source IP:   {v.get('source_ip') or '—'}\n"
            f"Username:    {v.get('username') or '—'}\n"
            f"Timestamp:   {ts}\n"
            f"Log Excerpt: {v.get('raw_log') or 'Not available'}\n"
            f"Action:      {v.get('recommended_action', '')}\n"
        )
        QApplication.clipboard().setText(text)
