"""CyberMon setup wizard — runs on first launch only.

Public helpers (no Qt dependency):
    is_first_run(config_path) -> bool
    write_wizard_config(settings, config_path) -> None

Qt classes (require QApplication):
    SetupWizard(QWizard)
"""
from __future__ import annotations

import os
import socket

import yaml


# ---------------------------------------------------------------------------
# Pure helpers — testable without QApplication
# ---------------------------------------------------------------------------

def is_first_run(config_path: str = "config/config.yaml") -> bool:
    """Return True if the wizard has never been completed for this config."""
    if not os.path.exists(config_path):
        return True
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}
    return not cfg.get("setup_complete", False)


def write_wizard_config(settings: dict, config_path: str = "config/config.yaml") -> None:
    """Merge wizard settings into config_path, creating the file if needed."""
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}

    cfg["mode"] = settings["mode"]
    cfg["setup_complete"] = True
    cfg["auth_log_path"] = settings.get("auth_log_path", "logs/auth.log")
    cfg["web_log_path"] = settings.get("web_log_path", "logs/access.log")

    # Detection thresholds
    cfg.setdefault("detection", {})
    cfg["detection"].setdefault("failed_logins", {})
    cfg["detection"]["failed_logins"]["threshold"] = settings.get("brute_force_threshold", 5)
    cfg["detection"]["failed_logins"]["time_window_minutes"] = settings.get("brute_force_window", 10)

    cfg["detection"].setdefault("off_hours_logins", {})
    cfg["detection"]["off_hours_logins"]["business_hours_start"] = settings.get("business_hours_start", "08:00")
    cfg["detection"]["off_hours_logins"]["business_hours_end"] = settings.get("business_hours_end", "18:00")
    cfg["detection"]["off_hours_logins"]["business_days"] = settings.get("business_days", [0, 1, 2, 3, 4])

    if settings["mode"] == "network":
        cfg.setdefault("server", {})
        cfg["server"]["ip"] = settings.get("server_ip", "0.0.0.0")
        cfg["server"]["port"] = settings.get("server_port", 5001)

    os.makedirs(os.path.dirname(os.path.abspath(config_path)), exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# Qt wizard — everything below requires a running QApplication
# ---------------------------------------------------------------------------

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)
from PyQt6.QtCore import QTime

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
_PURPLE     = "#7c3aed"
_DARK_BG    = "#1e1e2e"
_CARD_BG    = "#ffffff"
_MUTED      = "#6b7280"
_TEXT       = "#1f2937"
_BORDER     = "#e5e7eb"

_BASE_STYLE = f"""
    QWizard {{ background: #f3f4f6; }}
    QWizardPage {{ background: #f3f4f6; }}
    QLabel {{ color: {_TEXT}; }}
    QLineEdit, QSpinBox, QTimeEdit {{
        border: 1px solid {_BORDER};
        border-radius: 4px;
        padding: 6px 8px;
        background: white;
        color: {_TEXT};
        font-size: 13px;
    }}
    QLineEdit:focus, QSpinBox:focus, QTimeEdit:focus {{
        border-color: {_PURPLE};
    }}
    QPushButton#action {{
        background: {_PURPLE};
        color: white;
        border: none;
        border-radius: 4px;
        padding: 7px 16px;
        font-size: 13px;
    }}
    QPushButton#action:hover {{ background: #6d28d9; }}
    QCheckBox {{ color: {_TEXT}; font-size: 13px; }}
"""


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {_MUTED}; font-size: 11px; font-weight: bold; letter-spacing: 0.5px;")
    return lbl


def _divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color: {_BORDER};")
    f.setFixedHeight(1)
    return f


# ---------------------------------------------------------------------------
# Page IDs
# ---------------------------------------------------------------------------
_PAGE_MODE       = 0
_PAGE_STANDALONE = 1
_PAGE_NETWORK    = 2
_PAGE_CONFIRM    = 3


# ---------------------------------------------------------------------------
# Page 1 — mode selection
# ---------------------------------------------------------------------------

class _ModeCard(QPushButton):
    """Large checkable card button for mode selection."""
    _STYLE = """
        QPushButton {{
            border: 2px solid {border};
            border-radius: 8px;
            background: white;
            color: #1f2937;
            text-align: left;
            padding: 20px 24px;
            font-size: 14px;
            font-weight: bold;
        }}
        QPushButton:hover {{ border-color: #7c3aed; }}
        QPushButton:checked {{
            border-color: #7c3aed;
            background: #f5f3ff;
        }}
    """

    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setMinimumHeight(90)
        self.setStyleSheet(self._STYLE.format(border="#e5e7eb"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #1f2937; background: transparent;")
        title_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        sub_lbl = QLabel(subtitle)
        sub_lbl.setStyleSheet(f"font-size: 12px; color: {_MUTED}; background: transparent;")
        sub_lbl.setWordWrap(True)
        sub_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout.addWidget(title_lbl)
        layout.addWidget(sub_lbl)


class ModePage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Welcome to CyberMon")
        self.setSubTitle("How would you like to use CyberMon?")
        self._selected_mode: str | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self._standalone_btn = _ModeCard(
            "Just this computer",
            "Monitor log files on this machine only. No network setup needed.",
        )
        self._network_btn = _ModeCard(
            "Monitor multiple computers",
            "Set up a central monitoring server. Other machines send logs here.",
        )

        self._standalone_btn.clicked.connect(lambda: self._select("standalone"))
        self._network_btn.clicked.connect(lambda: self._select("network"))

        layout.addWidget(self._standalone_btn)
        layout.addWidget(self._network_btn)
        layout.addStretch()

    def _select(self, mode: str) -> None:
        self._selected_mode = mode
        self._standalone_btn.setChecked(mode == "standalone")
        self._network_btn.setChecked(mode == "network")
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._selected_mode is not None

    def nextId(self) -> int:
        if self._selected_mode == "network":
            return _PAGE_NETWORK
        return _PAGE_STANDALONE


# ---------------------------------------------------------------------------
# Shared business hours / threshold widget
# ---------------------------------------------------------------------------

class _CommonFields(QWidget):
    """Business hours and brute-force threshold fields shared by both config pages."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(_section_label("BUSINESS HOURS"))

        hours_row = QHBoxLayout()
        self._start = QTimeEdit(QTime(8, 0))
        self._start.setDisplayFormat("HH:mm")
        self._end = QTimeEdit(QTime(18, 0))
        self._end.setDisplayFormat("HH:mm")
        hours_row.addWidget(QLabel("Start"))
        hours_row.addWidget(self._start)
        hours_row.addSpacing(16)
        hours_row.addWidget(QLabel("End"))
        hours_row.addWidget(self._end)
        hours_row.addStretch()
        layout.addLayout(hours_row)

        days_row = QHBoxLayout()
        days_row.setSpacing(8)
        self._day_checks: list[QCheckBox] = []
        for label in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            cb = QCheckBox(label)
            cb.setChecked(label not in ("Sat", "Sun"))
            self._day_checks.append(cb)
            days_row.addWidget(cb)
        days_row.addStretch()
        layout.addLayout(days_row)

        layout.addSpacing(4)
        layout.addWidget(_section_label("BRUTE FORCE DETECTION"))

        thresh_row = QHBoxLayout()
        self._threshold = QSpinBox()
        self._threshold.setRange(1, 100)
        self._threshold.setValue(5)
        self._window = QSpinBox()
        self._window.setRange(1, 1440)
        self._window.setValue(10)
        thresh_row.addWidget(QLabel("Failed attempts"))
        thresh_row.addWidget(self._threshold)
        thresh_row.addSpacing(16)
        thresh_row.addWidget(QLabel("within (minutes)"))
        thresh_row.addWidget(self._window)
        thresh_row.addStretch()
        layout.addLayout(thresh_row)

    def get_values(self) -> dict:
        days = [i for i, cb in enumerate(self._day_checks) if cb.isChecked()]
        return {
            "business_hours_start": self._start.time().toString("HH:mm"),
            "business_hours_end": self._end.time().toString("HH:mm"),
            "business_days": days,
            "brute_force_threshold": self._threshold.value(),
            "brute_force_window": self._window.value(),
        }


# ---------------------------------------------------------------------------
# Page 2a — standalone configuration
# ---------------------------------------------------------------------------

class StandalonePage(QWizardPage):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setTitle("Where are your log files?")
        self.setSubTitle("CyberMon will watch these files for security events.")

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(_section_label("LOG FILE PATHS"))

        # Auth log
        auth_row = QHBoxLayout()
        self._auth_input = QLineEdit(config.get("auth_log_path", "logs/auth.log"))
        auth_browse = QPushButton("Browse")
        auth_browse.setObjectName("action")
        auth_browse.setFixedWidth(70)
        auth_browse.clicked.connect(lambda: self._browse(self._auth_input))
        self._auth_status = QLabel()
        self._auth_status.setFixedWidth(20)
        auth_row.addWidget(QLabel("Auth log:"))
        auth_row.addWidget(self._auth_input)
        auth_row.addWidget(auth_browse)
        auth_row.addWidget(self._auth_status)
        layout.addLayout(auth_row)

        # Web access log
        web_row = QHBoxLayout()
        self._web_input = QLineEdit(config.get("web_log_path", "logs/access.log"))
        web_browse = QPushButton("Browse")
        web_browse.setObjectName("action")
        web_browse.setFixedWidth(70)
        web_browse.clicked.connect(lambda: self._browse(self._web_input))
        self._web_status = QLabel()
        self._web_status.setFixedWidth(20)
        web_row.addWidget(QLabel("Web log:  "))
        web_row.addWidget(self._web_input)
        web_row.addWidget(web_browse)
        web_row.addWidget(self._web_status)
        layout.addLayout(web_row)

        test_btn = QPushButton("Test paths")
        test_btn.setObjectName("action")
        test_btn.setFixedWidth(100)
        test_btn.clicked.connect(self._test_paths)
        layout.addWidget(test_btn)

        layout.addWidget(_divider())

        self._common = _CommonFields()
        layout.addWidget(self._common)
        layout.addStretch()

    def _browse(self, field: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select log file", "", "Log files (*.log);;All files (*)")
        if path:
            field.setText(path)

    def _test_paths(self) -> None:
        for field, status in ((self._auth_input, self._auth_status), (self._web_input, self._web_status)):
            exists = os.path.exists(field.text())
            status.setText("✓" if exists else "✗")
            status.setStyleSheet("color: green; font-size: 15px;" if exists else "color: red; font-size: 15px;")

    def get_values(self) -> dict:
        d = {
            "auth_log_path": self._auth_input.text(),
            "web_log_path": self._web_input.text(),
        }
        d.update(self._common.get_values())
        return d

    def nextId(self) -> int:
        return _PAGE_CONFIRM


# ---------------------------------------------------------------------------
# Page 2b — network configuration
# ---------------------------------------------------------------------------

class NetworkPage(QWizardPage):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setTitle("Set up your monitoring server")
        self.setSubTitle("Other machines will send their logs to this computer.")

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Auto-detect local IP
        try:
            detected_ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            detected_ip = "127.0.0.1"

        layout.addWidget(_section_label("SERVER ADDRESS"))

        ip_row = QHBoxLayout()
        ip_row.addWidget(QLabel("This machine's IP:"))
        self._ip_input = QLineEdit(detected_ip)
        ip_row.addWidget(self._ip_input)
        layout.addLayout(ip_row)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port:"))
        self._port = QSpinBox()
        self._port.setRange(1024, 65535)
        self._port.setValue(config.get("server", {}).get("port", 5001))
        port_row.addWidget(self._port)
        port_row.addStretch()
        layout.addLayout(port_row)

        info = QLabel(
            "Install CyberMonAgent.exe on each computer you want to monitor.\n"
            "Enter this server's IP address when the agent asks."
        )
        info.setStyleSheet(f"color: {_MUTED}; font-size: 12px; background: #eff6ff; "
                           "border: 1px solid #bfdbfe; border-radius: 4px; padding: 8px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addWidget(_divider())

        self._common = _CommonFields()
        layout.addWidget(self._common)
        layout.addStretch()

    def get_values(self) -> dict:
        d = {
            "server_ip": self._ip_input.text(),
            "server_port": self._port.value(),
        }
        d.update(self._common.get_values())
        return d

    def nextId(self) -> int:
        return _PAGE_CONFIRM


# ---------------------------------------------------------------------------
# Page 3 — confirmation
# ---------------------------------------------------------------------------

class ConfirmPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("You're all set")
        self.setSubTitle("Review your settings and click Finish to start monitoring.")
        self._summary_lbl = QLabel()
        self._summary_lbl.setWordWrap(True)
        self._summary_lbl.setStyleSheet(
            "background: white; border: 1px solid #e5e7eb; border-radius: 6px; "
            "padding: 16px; font-size: 13px; color: #1f2937; line-height: 160%;"
        )
        layout = QVBoxLayout(self)
        layout.addWidget(self._summary_lbl)
        layout.addStretch()

    def initializePage(self) -> None:
        wiz: SetupWizard = self.wizard()
        s = wiz.collected_settings()
        lines = [f"<b>Mode:</b> {s['mode']}"]
        if s["mode"] == "standalone":
            lines.append(f"<b>Auth log:</b> {s.get('auth_log_path', '')}")
            lines.append(f"<b>Web log:</b> {s.get('web_log_path', '')}")
        else:
            lines.append(f"<b>Server IP:</b> {s.get('server_ip', '')}")
            lines.append(f"<b>Server port:</b> {s.get('server_port', '')}")
        lines.append(
            f"<b>Business hours:</b> {s.get('business_hours_start', '08:00')} – "
            f"{s.get('business_hours_end', '18:00')}"
        )
        lines.append(
            f"<b>Brute force threshold:</b> {s.get('brute_force_threshold', 5)} attempts "
            f"in {s.get('brute_force_window', 10)} minutes"
        )
        self._summary_lbl.setText("<br>".join(lines))

    def nextId(self) -> int:
        return -1


# ---------------------------------------------------------------------------
# SetupWizard
# ---------------------------------------------------------------------------

class SetupWizard(QWizard):
    def __init__(self, config: dict, config_path: str = "config/config.yaml", parent=None):
        super().__init__(parent)
        self._config_path = config_path
        self.setWindowTitle("CyberMon Setup")
        self.setMinimumSize(600, 480)
        self.setStyleSheet(_BASE_STYLE)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)

        self._mode_page = ModePage()
        self._standalone_page = StandalonePage(config)
        self._network_page = NetworkPage(config)
        self._confirm_page = ConfirmPage()

        self.setPage(_PAGE_MODE,       self._mode_page)
        self.setPage(_PAGE_STANDALONE, self._standalone_page)
        self.setPage(_PAGE_NETWORK,    self._network_page)
        self.setPage(_PAGE_CONFIRM,    self._confirm_page)
        self.setStartId(_PAGE_MODE)

    def collected_settings(self) -> dict:
        mode = self._mode_page._selected_mode or "standalone"
        d = {"mode": mode}
        if mode == "network":
            d.update(self._network_page.get_values())
        else:
            d.update(self._standalone_page.get_values())
        return d

    def accept(self) -> None:
        write_wizard_config(self.collected_settings(), self._config_path)
        super().accept()
