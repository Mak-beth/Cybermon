"""CyberMon setup wizard — runs on first launch only.

Public helpers (no Qt dependency — safe to import anywhere):
    is_first_run(config_path) -> bool
    write_wizard_config(settings, config_path) -> None

Qt factory (imports PyQt6 only when first called):
    SetupWizard(config, config_path, parent) -> QWizard instance
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
# Deferred Qt wizard — PyQt6 is imported only when SetupWizard() is called
# ---------------------------------------------------------------------------

_wizard_class = None   # cached after first _build_wizard() call


def _build_wizard():
    """Define and return the real QWizard class with all Qt imports local."""
    from PyQt6.QtCore import QTime, Qt
    from PyQt6.QtWidgets import (
        QCheckBox,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QSpinBox,
        QTimeEdit,
        QVBoxLayout,
        QWidget,
        QWizard,
        QWizardPage,
    )

    # Palette
    _PURPLE = "#7c3aed"
    _MUTED  = "#6b7280"
    _TEXT   = "#1f2937"
    _BORDER = "#e5e7eb"

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

    def _section_label(text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {_MUTED}; font-size: 11px; font-weight: bold; letter-spacing: 0.5px;"
        )
        return lbl

    def _divider():
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(f"color: {_BORDER};")
        f.setFixedHeight(1)
        return f

    # Page IDs
    _PAGE_MODE       = 0
    _PAGE_STANDALONE = 1
    _PAGE_NETWORK    = 2
    _PAGE_CONFIRM    = 3

    class _ModeCard(QPushButton):
        _STYLE = """
            QPushButton {
                border: 2px solid #e5e7eb;
                border-radius: 8px;
                background: white;
                color: #1f2937;
                text-align: left;
                padding: 20px 24px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover  { border-color: #7c3aed; }
            QPushButton:checked { border-color: #7c3aed; background: #f5f3ff; }
        """

        def __init__(self, title, subtitle, parent=None):
            super().__init__(parent)
            self.setCheckable(True)
            self.setMinimumHeight(90)
            self.setStyleSheet(self._STYLE)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(4, 4, 4, 4)
            layout.setSpacing(4)
            t = QLabel(title)
            t.setStyleSheet(
                "font-size: 15px; font-weight: bold; color: #1f2937; background: transparent;"
            )
            t.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            s = QLabel(subtitle)
            s.setStyleSheet(f"font-size: 12px; color: {_MUTED}; background: transparent;")
            s.setWordWrap(True)
            s.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(t)
            layout.addWidget(s)

    class _CommonFields(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            layout.addWidget(_section_label("BUSINESS HOURS"))
            hr = QHBoxLayout()
            self._start = QTimeEdit(QTime(8, 0))
            self._start.setDisplayFormat("HH:mm")
            self._end = QTimeEdit(QTime(18, 0))
            self._end.setDisplayFormat("HH:mm")
            hr.addWidget(QLabel("Start"))
            hr.addWidget(self._start)
            hr.addSpacing(16)
            hr.addWidget(QLabel("End"))
            hr.addWidget(self._end)
            hr.addStretch()
            layout.addLayout(hr)
            dr = QHBoxLayout()
            dr.setSpacing(8)
            self._day_checks = []
            for label in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
                cb = QCheckBox(label)
                cb.setChecked(label not in ("Sat", "Sun"))
                self._day_checks.append(cb)
                dr.addWidget(cb)
            dr.addStretch()
            layout.addLayout(dr)
            layout.addSpacing(4)
            layout.addWidget(_section_label("BRUTE FORCE DETECTION"))
            tr = QHBoxLayout()
            self._threshold = QSpinBox()
            self._threshold.setRange(1, 100)
            self._threshold.setValue(5)
            self._window = QSpinBox()
            self._window.setRange(1, 1440)
            self._window.setValue(10)
            tr.addWidget(QLabel("Failed attempts"))
            tr.addWidget(self._threshold)
            tr.addSpacing(16)
            tr.addWidget(QLabel("within (minutes)"))
            tr.addWidget(self._window)
            tr.addStretch()
            layout.addLayout(tr)

        def get_values(self):
            return {
                "business_hours_start": self._start.time().toString("HH:mm"),
                "business_hours_end": self._end.time().toString("HH:mm"),
                "business_days": [i for i, cb in enumerate(self._day_checks) if cb.isChecked()],
                "brute_force_threshold": self._threshold.value(),
                "brute_force_window": self._window.value(),
            }

    class _ModePage(QWizardPage):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setTitle("Welcome to CyberMon")
            self.setSubTitle("How would you like to use CyberMon?")
            self._selected_mode = None
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

        def _select(self, mode):
            self._selected_mode = mode
            self._standalone_btn.setChecked(mode == "standalone")
            self._network_btn.setChecked(mode == "network")
            self.completeChanged.emit()

        def isComplete(self):
            return self._selected_mode is not None

        def nextId(self):
            if self._selected_mode == "network":
                return _PAGE_NETWORK
            return _PAGE_STANDALONE

    class _StandalonePage(QWizardPage):
        def __init__(self, config, parent=None):
            super().__init__(parent)
            self.setTitle("Where are your log files?")
            self.setSubTitle("CyberMon will watch these files for security events.")
            layout = QVBoxLayout(self)
            layout.setSpacing(8)
            layout.addWidget(_section_label("LOG FILE PATHS"))

            self._auth_input = QLineEdit(config.get("auth_log_path", "logs/auth.log"))
            self._auth_status = QLabel()
            self._auth_status.setFixedWidth(20)
            ar = QHBoxLayout()
            ar.addWidget(QLabel("Auth log:"))
            ar.addWidget(self._auth_input)
            ab = QPushButton("Browse")
            ab.setObjectName("action")
            ab.setFixedWidth(70)
            ab.clicked.connect(lambda: self._browse(self._auth_input))
            ar.addWidget(ab)
            ar.addWidget(self._auth_status)
            layout.addLayout(ar)

            self._web_input = QLineEdit(config.get("web_log_path", "logs/access.log"))
            self._web_status = QLabel()
            self._web_status.setFixedWidth(20)
            wr = QHBoxLayout()
            wr.addWidget(QLabel("Web log:  "))
            wr.addWidget(self._web_input)
            wb = QPushButton("Browse")
            wb.setObjectName("action")
            wb.setFixedWidth(70)
            wb.clicked.connect(lambda: self._browse(self._web_input))
            wr.addWidget(wb)
            wr.addWidget(self._web_status)
            layout.addLayout(wr)

            test_btn = QPushButton("Test paths")
            test_btn.setObjectName("action")
            test_btn.setFixedWidth(100)
            test_btn.clicked.connect(self._test_paths)
            layout.addWidget(test_btn)
            layout.addWidget(_divider())

            self._common = _CommonFields()
            layout.addWidget(self._common)
            layout.addStretch()

        def _browse(self, field):
            path, _ = QFileDialog.getOpenFileName(
                self, "Select log file", "", "Log files (*.log);;All files (*)"
            )
            if path:
                field.setText(path)

        def _test_paths(self):
            for field, status in (
                (self._auth_input, self._auth_status),
                (self._web_input, self._web_status),
            ):
                exists = os.path.exists(field.text())
                status.setText("+" if exists else "x")
                status.setStyleSheet(
                    "color: green; font-size: 15px; font-weight: bold;"
                    if exists else
                    "color: red; font-size: 15px; font-weight: bold;"
                )

        def get_values(self):
            d = {
                "auth_log_path": self._auth_input.text(),
                "web_log_path": self._web_input.text(),
            }
            d.update(self._common.get_values())
            return d

        def nextId(self):
            return _PAGE_CONFIRM

    class _NetworkPage(QWizardPage):
        def __init__(self, config, parent=None):
            super().__init__(parent)
            self.setTitle("Set up your monitoring server")
            self.setSubTitle("Other machines will send their logs to this computer.")
            layout = QVBoxLayout(self)
            layout.setSpacing(8)
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
            info.setStyleSheet(
                f"color: {_MUTED}; font-size: 12px; background: #eff6ff;"
                " border: 1px solid #bfdbfe; border-radius: 4px; padding: 8px;"
            )
            info.setWordWrap(True)
            layout.addWidget(info)
            layout.addWidget(_divider())
            self._common = _CommonFields()
            layout.addWidget(self._common)
            layout.addStretch()

        def get_values(self):
            d = {
                "server_ip": self._ip_input.text(),
                "server_port": self._port.value(),
            }
            d.update(self._common.get_values())
            return d

        def nextId(self):
            return _PAGE_CONFIRM

    class _ConfirmPage(QWizardPage):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setTitle("You're all set")
            self.setSubTitle("Review your settings and click Finish to start monitoring.")
            self._summary = QLabel()
            self._summary.setWordWrap(True)
            self._summary.setStyleSheet(
                "background: white; border: 1px solid #e5e7eb; border-radius: 6px;"
                " padding: 16px; font-size: 13px; color: #1f2937;"
            )
            layout = QVBoxLayout(self)
            layout.addWidget(self._summary)
            layout.addStretch()

        def initializePage(self):
            wiz = self.wizard()
            s = wiz._collected_settings()
            lines = [f"<b>Mode:</b> {s['mode']}"]
            if s["mode"] == "standalone":
                lines.append(f"<b>Auth log:</b> {s.get('auth_log_path', '')}")
                lines.append(f"<b>Web log:</b> {s.get('web_log_path', '')}")
            else:
                lines.append(f"<b>Server IP:</b> {s.get('server_ip', '')}")
                lines.append(f"<b>Server port:</b> {s.get('server_port', '')}")
            lines.append(
                f"<b>Business hours:</b> {s.get('business_hours_start', '08:00')} - "
                f"{s.get('business_hours_end', '18:00')}"
            )
            lines.append(
                f"<b>Brute force threshold:</b> {s.get('brute_force_threshold', 5)} attempts "
                f"in {s.get('brute_force_window', 10)} minutes"
            )
            self._summary.setText("<br>".join(lines))

        def nextId(self):
            return -1

    class _RealSetupWizard(QWizard):
        def __init__(self, config, config_path="config/config.yaml", parent=None):
            super().__init__(parent)
            self._config_path = config_path
            self.setWindowTitle("CyberMon Setup")
            self.setMinimumSize(600, 480)
            self.setStyleSheet(_BASE_STYLE)
            self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
            self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)

            self._mode_page       = _ModePage()
            self._standalone_page = _StandalonePage(config)
            self._network_page    = _NetworkPage(config)
            self._confirm_page    = _ConfirmPage()

            self.setPage(_PAGE_MODE,       self._mode_page)
            self.setPage(_PAGE_STANDALONE, self._standalone_page)
            self.setPage(_PAGE_NETWORK,    self._network_page)
            self.setPage(_PAGE_CONFIRM,    self._confirm_page)
            self.setStartId(_PAGE_MODE)

        def _collected_settings(self):
            mode = self._mode_page._selected_mode or "standalone"
            d = {"mode": mode}
            if mode == "network":
                d.update(self._network_page.get_values())
            else:
                d.update(self._standalone_page.get_values())
            return d

        def accept(self):
            write_wizard_config(self._collected_settings(), self._config_path)
            super().accept()

    return _RealSetupWizard


def SetupWizard(config: dict, config_path: str = "config/config.yaml", parent=None):
    """Factory: lazily build the Qt wizard class and return an instance.

    Calling this function is the only thing that imports PyQt6.  The pure
    helpers (is_first_run, write_wizard_config) remain importable without
    any Qt installation present.
    """
    global _wizard_class
    if _wizard_class is None:
        _wizard_class = _build_wizard()
    return _wizard_class(config, config_path=config_path, parent=parent)
