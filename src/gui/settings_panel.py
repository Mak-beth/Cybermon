"""CyberMon settings panel — available from the sidebar at any time.

Shows current config values and allows saving changes.  Also provides
a button to reset setup_complete so the wizard runs on next launch.
Emits theme_changed(str) when the user saves a new theme preference.
"""
from __future__ import annotations

import os

import yaml
from PyQt6.QtCore import QTime, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from src.gui import theme as _theme

_PURPLE = "#7c3aed"
_BORDER = "#e5e7eb"


def _make_style(palette: dict) -> str:
    bg    = palette["content_bg"]
    card  = palette["card_bg"]
    text  = palette["text_primary"]
    muted = palette["text_secondary"]
    bdr   = palette["border"]
    inp   = palette["input_bg"]
    return f"""
    QWidget#settings_root {{ background: {bg}; }}
    QFrame#card {{
        background: {card};
        border: 1px solid {bdr};
        border-radius: 8px;
    }}
    QLabel {{ color: {text}; font-size: 13px; }}
    QLabel#section {{
        color: {muted};
        font-size: 11px;
        font-weight: bold;
        letter-spacing: 0.5px;
    }}
    QLineEdit, QSpinBox, QTimeEdit, QComboBox {{
        border: 1px solid {bdr};
        border-radius: 4px;
        padding: 5px 8px;
        background: {inp};
        color: {text};
        font-size: 13px;
    }}
    QLineEdit:focus, QSpinBox:focus, QTimeEdit:focus, QComboBox:focus {{
        border-color: {_PURPLE};
    }}
    QSpinBox::up-button, QTimeEdit::up-button {{
        subcontrol-origin: border;
        subcontrol-position: top right;
        width: 20px;
        border-left: 1px solid {bdr};
        border-bottom: 1px solid {bdr};
        border-top-right-radius: 4px;
        background: {card};
    }}
    QSpinBox::up-button:hover, QTimeEdit::up-button:hover {{ background: {bdr}; }}
    QSpinBox::up-button:pressed, QTimeEdit::up-button:pressed {{ background: {muted}; }}
    QSpinBox::down-button, QTimeEdit::down-button {{
        subcontrol-origin: border;
        subcontrol-position: bottom right;
        width: 20px;
        border-left: 1px solid {bdr};
        border-top: 1px solid {bdr};
        border-bottom-right-radius: 4px;
        background: {card};
    }}
    QSpinBox::down-button:hover, QTimeEdit::down-button:hover {{ background: {bdr}; }}
    QSpinBox::down-button:pressed, QTimeEdit::down-button:pressed {{ background: {muted}; }}
    QSpinBox::up-arrow, QTimeEdit::up-arrow {{ width: 8px; height: 8px; }}
    QSpinBox::down-arrow, QTimeEdit::down-arrow {{ width: 8px; height: 8px; }}
    QPushButton#save {{
        background: {_PURPLE};
        color: white;
        border: none;
        border-radius: 4px;
        padding: 8px 20px;
        font-size: 13px;
        font-weight: bold;
    }}
    QPushButton#save:hover {{ background: #6d28d9; }}
    QPushButton#rerun {{
        background: {card};
        color: {muted};
        border: 1px solid {bdr};
        border-radius: 4px;
        padding: 8px 20px;
        font-size: 13px;
    }}
    QPushButton#rerun:hover {{ background: {bdr}; }}
    QCheckBox {{ color: {text}; font-size: 13px; }}
    """


def _section(text: str, palette: dict) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")
    lbl.setStyleSheet(
        f"color: {palette['text_secondary']}; font-size: 11px; font-weight: bold; letter-spacing: 0.5px;"
    )
    return lbl


def _divider(palette: dict) -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color: {palette['border']};")
    f.setFixedHeight(1)
    return f


class SettingsPanel(QWidget):
    # Class-level signal — must be here, not inside __init__ or any method.
    # PyQt6 signals are class-level descriptors; declaring them inside a method
    # creates a plain attribute that silently fails to connect.
    theme_changed = pyqtSignal(str)

    def __init__(self, config: dict, config_path: str = "config/config.yaml", parent=None):
        super().__init__(parent)
        self._config_path = config_path
        self._palette = _theme.get_active()
        self.setObjectName("settings_root")
        self.setStyleSheet(_make_style(self._palette))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        title = QLabel("Settings")
        title.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {self._palette['text_primary']};"
        )
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        content = QVBoxLayout(inner)
        content.setSpacing(16)
        content.setContentsMargins(0, 0, 0, 0)

        self._build_fields(config, content)
        content.addStretch()

        scroll.setWidget(inner)
        outer.addWidget(scroll)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save changes")
        save_btn.setObjectName("save")
        save_btn.clicked.connect(self._save)
        rerun_btn = QPushButton("Re-run Setup Wizard")
        rerun_btn.setObjectName("rerun")
        rerun_btn.clicked.connect(self._reset_wizard)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(rerun_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Field construction
    # ------------------------------------------------------------------

    def _build_fields(self, cfg: dict, layout: QVBoxLayout) -> None:
        p = self._palette
        detection = cfg.get("detection", {})
        failed    = detection.get("failed_logins", {})
        off_hours = detection.get("off_hours_logins", {})

        # Log paths card
        paths_card = self._card()
        paths_layout = paths_card.layout()
        paths_layout.addWidget(_section("LOG FILE PATHS", p))
        self._auth_input = QLineEdit(cfg.get("auth_log_path", "logs/auth.log"))
        paths_layout.addLayout(self._browse_row("Auth log", self._auth_input))
        self._web_input = QLineEdit(cfg.get("web_log_path", "logs/access.log"))
        paths_layout.addLayout(self._browse_row("Web log", self._web_input))
        layout.addWidget(paths_card)

        # Business hours card
        hours_card = self._card()
        hours_layout = hours_card.layout()
        hours_layout.addWidget(_section("BUSINESS HOURS", p))

        start_str = off_hours.get("business_hours_start", "08:00")
        end_str   = off_hours.get("business_hours_end",   "18:00")
        sh, sm = (int(x) for x in start_str.split(":"))
        eh, em = (int(x) for x in end_str.split(":"))
        self._start = QTimeEdit(QTime(sh, sm))
        self._start.setDisplayFormat("HH:mm")
        self._end = QTimeEdit(QTime(eh, em))
        self._end.setDisplayFormat("HH:mm")

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Start"))
        time_row.addWidget(self._start)
        time_row.addSpacing(16)
        time_row.addWidget(QLabel("End"))
        time_row.addWidget(self._end)
        time_row.addStretch()
        hours_layout.addLayout(time_row)

        saved_days = off_hours.get("business_days", [0, 1, 2, 3, 4])
        days_row = QHBoxLayout()
        days_row.setSpacing(8)
        self._day_checks: list[QCheckBox] = []
        for i, label in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
            cb = QCheckBox(label)
            cb.setChecked(i in saved_days)
            self._day_checks.append(cb)
            days_row.addWidget(cb)
        days_row.addStretch()
        hours_layout.addLayout(days_row)
        layout.addWidget(hours_card)

        # Detection thresholds card
        thresh_card = self._card()
        thresh_layout = thresh_card.layout()
        thresh_layout.addWidget(_section("BRUTE FORCE DETECTION", p))
        self._threshold = QSpinBox()
        self._threshold.setRange(1, 100)
        self._threshold.setValue(failed.get("threshold", 5))
        self._window = QSpinBox()
        self._window.setRange(1, 1440)
        self._window.setValue(failed.get("time_window_minutes", 10))
        thresh_row = QHBoxLayout()
        thresh_row.addWidget(QLabel("Failed attempts"))
        thresh_row.addWidget(self._threshold)
        thresh_row.addSpacing(16)
        thresh_row.addWidget(QLabel("within (minutes)"))
        thresh_row.addWidget(self._window)
        thresh_row.addStretch()
        thresh_layout.addLayout(thresh_row)
        layout.addWidget(thresh_card)

        # Appearance card
        appear_card = self._card()
        appear_layout = appear_card.layout()
        appear_layout.addWidget(_section("APPEARANCE", p))
        theme_row = QHBoxLayout()
        theme_lbl = QLabel("Theme:")
        theme_row.addWidget(theme_lbl)
        self._theme_combo = QComboBox()
        self._theme_combo.addItem("Light")
        self._theme_combo.addItem("Dark")
        current_theme = cfg.get("ui", {}).get("theme", _theme.get_active_name())
        self._theme_combo.setCurrentText(current_theme.capitalize())
        self._theme_combo.setFixedWidth(120)
        theme_row.addWidget(self._theme_combo)
        theme_row.addStretch()
        appear_layout.addLayout(theme_row)
        layout.addWidget(appear_card)

    def _card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)
        return card

    def _browse_row(self, label_text: str, field: QLineEdit) -> QHBoxLayout:
        row = QHBoxLayout()
        lbl = QLabel(f"{label_text}:")
        lbl.setFixedWidth(60)
        browse = QPushButton("Browse")
        browse.setObjectName("save")
        browse.setFixedWidth(70)
        browse.clicked.connect(lambda: self._browse(field))
        row.addWidget(lbl)
        row.addWidget(field)
        row.addWidget(browse)
        return row

    def _browse(self, field: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select log file", "", "Log files (*.log);;All files (*)"
        )
        if path:
            field.setText(path)

    # ------------------------------------------------------------------
    # Theme support
    # ------------------------------------------------------------------

    def apply_theme(self, palette: dict) -> None:
        self._palette = palette
        self.setStyleSheet(_make_style(palette))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _save(self) -> None:
        if not os.path.exists(self._config_path):
            QMessageBox.warning(self, "Config not found", f"Cannot find {self._config_path}.")
            return

        with open(self._config_path) as f:
            cfg = yaml.safe_load(f) or {}

        cfg["auth_log_path"] = self._auth_input.text()
        cfg["web_log_path"]  = self._web_input.text()

        cfg.setdefault("detection", {})
        cfg["detection"].setdefault("failed_logins", {})
        cfg["detection"]["failed_logins"]["threshold"]           = self._threshold.value()
        cfg["detection"]["failed_logins"]["time_window_minutes"] = self._window.value()

        cfg["detection"].setdefault("off_hours_logins", {})
        cfg["detection"]["off_hours_logins"]["business_hours_start"] = (
            self._start.time().toString("HH:mm")
        )
        cfg["detection"]["off_hours_logins"]["business_hours_end"] = (
            self._end.time().toString("HH:mm")
        )
        cfg["detection"]["off_hours_logins"]["business_days"] = [
            i for i, cb in enumerate(self._day_checks) if cb.isChecked()
        ]

        # Theme preference
        new_theme_name = self._theme_combo.currentText().lower()
        cfg.setdefault("ui", {})
        cfg["ui"]["theme"] = new_theme_name

        with open(self._config_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

        # Apply new theme immediately (signal connects to MainWindow.apply_theme)
        _theme.set_active(new_theme_name)
        self.theme_changed.emit(new_theme_name)

        QMessageBox.information(
            self, "Saved",
            "Settings saved. Detection threshold changes take effect on the next pipeline run."
        )

    def _reset_wizard(self) -> None:
        if not os.path.exists(self._config_path):
            QMessageBox.warning(self, "Config not found", f"Cannot find {self._config_path}.")
            return

        with open(self._config_path) as f:
            cfg = yaml.safe_load(f) or {}

        cfg["setup_complete"] = False

        with open(self._config_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

        QMessageBox.information(
            self,
            "Wizard Reset",
            "The setup wizard will run the next time CyberMon is launched.",
        )
