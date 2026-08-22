"""CyberMon settings panel — available from the sidebar at any time.

Shows current config values and allows saving changes.  Also provides
a button to reset setup_complete so the wizard runs on next launch.
Emits theme_changed(str) when the user saves a new theme preference.
"""
from __future__ import annotations

import logging
import os

import yaml
from PyQt6.QtCore import QTime, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from src.gui import config_io
from src.gui import theme as _theme
from src.storage.rescore import rescore_violations

logger = logging.getLogger(__name__)

def _section(text: str, palette: dict) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")   # themed by the app stylesheet
    return lbl


def _divider(palette: dict) -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setObjectName("divider")   # themed by the app stylesheet
    f.setFixedHeight(1)
    return f


class SettingsPanel(QWidget):
    # Class-level signal — must be here, not inside __init__ or any method.
    # PyQt6 signals are class-level descriptors; declaring them inside a method
    # creates a plain attribute that silently fails to connect.
    theme_changed = pyqtSignal(str)
    # Emitted after a successful re-score so MainWindow can refresh data panels.
    rescored = pyqtSignal()

    def __init__(self, config: dict, config_path: str = "config/config.yaml", parent=None):
        super().__init__(parent)
        self._config_path = config_path
        self._palette = _theme.get_active()
        self._rescoring = False
        self.setObjectName("settings_root")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        title = QLabel("Settings")
        title.setObjectName("panelTitle")
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
        self._save_btn = QPushButton("Save changes")
        self._save_btn.setObjectName("save")
        self._save_btn.clicked.connect(self._save)
        # "&&" escapes the ampersand so Qt does not read it as a mnemonic.
        self._rescore_btn = QPushButton("Save && Re-score")
        self._rescore_btn.setObjectName("save")
        self._rescore_btn.setToolTip(
            "Save, then recalculate scores for violations already detected. "
            "Detection changes still need a restart."
        )
        self._rescore_btn.clicked.connect(self._save_and_rescore)
        rerun_btn = QPushButton("Re-run Setup Wizard")
        rerun_btn.setObjectName("rerun")
        rerun_btn.clicked.connect(self._reset_wizard)
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._rescore_btn)
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

        # Risk scoring rules card (R11-C)
        scoring_rules = cfg.get("scoring", {}).get("rules", {})
        scoring_card = self._card()
        scoring_layout = scoring_card.layout()
        scoring_layout.addWidget(_section("RISK SCORING RULES", p))

        def _list_field(label_text: str, values: list) -> QPlainTextEdit:
            row_lbl = QLabel(label_text)
            scoring_layout.addWidget(row_lbl)
            field = QPlainTextEdit()
            field.setPlainText(", ".join(values))
            field.setFixedHeight(52)
            scoring_layout.addWidget(field)
            return field

        self._high_users_input = _list_field(
            "High-impact users (comma-separated):",
            scoring_rules.get("high_impact_users", ["root", "admin"]),
        )
        self._high_resources_input = _list_field(
            "High-impact resources (one per line or comma-separated):",
            scoring_rules.get("high_impact_resources",
                              ["/admin", "/.env", "/phpmyadmin"]),
        )
        self._med_resources_input = _list_field(
            "Medium-impact resources:",
            scoring_rules.get("med_impact_resources", ["/config", "/wp-admin"]),
        )

        # --- numeric scoring values (likelihood / impact, 1-5) ---
        def _score_row(parent_layout, label_text, key, default):
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setObjectName("fieldLabel")
            lbl.setMinimumWidth(300)
            row.addWidget(lbl)
            box = QSpinBox()
            box.setRange(config_io.SCORE_MIN, config_io.SCORE_MAX)
            value = scoring_rules.get(key, default)
            box.setValue(value if isinstance(value, int) else default)
            box.setFixedWidth(70)
            row.addWidget(box)
            row.addStretch()
            parent_layout.addLayout(row)
            return box

        scoring_layout.addWidget(_section("SCORE VALUES (1-5)", p))
        self._score_inputs = {}
        for label_text, key, default in (
            ("Failed logins - privileged user impact", "failed_login_high_user_impact", 4),
            ("Failed logins - standard user impact",   "failed_login_default_impact", 2),
            ("Unauthorized access - likelihood",       "unauthorized_access_default_likelihood", 3),
            ("Unauthorized access - high resource impact",
             "unauthorized_access_high_resource_impact", 5),
            ("Unauthorized access - medium resource impact",
             "unauthorized_access_med_resource_impact", 3),
            ("Unauthorized access - other resource impact",
             "unauthorized_access_default_impact", 2),
            ("Off-hours login - likelihood",           "off_hours_default_likelihood", 2),
            ("Off-hours login - privileged user impact", "off_hours_high_user_impact", 5),
            ("Off-hours login - standard user impact", "off_hours_default_impact", 3),
        ):
            self._score_inputs[key] = _score_row(scoring_layout, label_text, key, default)

        layout.addWidget(scoring_card)

        # --- Severity tier boundaries ---
        tiers_cfg = cfg.get("scoring", {}).get("severity_tiers", {}) or {}
        tiers_card = self._card()
        tiers_layout = tiers_card.layout()
        tiers_layout.addWidget(_section("SEVERITY TIER BOUNDARIES", p))

        self._tier_inputs = {}
        for tier_name, fallback in (
            ("low", {"min": 1, "max": 4}), ("medium", {"min": 5, "max": 9}),
            ("high", {"min": 10, "max": 16}), ("critical", {"min": 17, "max": 25}),
        ):
            tier = tiers_cfg.get(tier_name, fallback) or fallback
            row = QHBoxLayout()
            name_lbl = QLabel(tier_name.capitalize())
            name_lbl.setObjectName("fieldLabel")
            name_lbl.setFixedWidth(90)
            row.addWidget(name_lbl)
            boxes = {}
            for bound in ("min", "max"):
                bound_lbl = QLabel(bound)
                bound_lbl.setObjectName("mutedText")
                row.addWidget(bound_lbl)
                box = QSpinBox()
                box.setRange(config_io.TIER_MIN, config_io.TIER_MAX)
                raw = tier.get(bound, fallback[bound])
                box.setValue(raw if isinstance(raw, int) else fallback[bound])
                box.setFixedWidth(70)
                row.addWidget(box)
                boxes[bound] = box
            row.addStretch()
            tiers_layout.addLayout(row)
            self._tier_inputs[tier_name] = boxes

        layout.addWidget(tiers_card)

        # --- Scoped restore-defaults buttons ---
        restore_card = self._card()
        restore_layout = restore_card.layout()
        restore_layout.addWidget(_section("RESTORE DEFAULTS", p))
        restore_note = QLabel(
            "Each button resets only its own section. Log file paths, setup "
            "status, mode, theme and server settings are never changed."
        )
        restore_note.setObjectName("mutedText")
        restore_note.setWordWrap(True)
        restore_layout.addWidget(restore_note)

        restore_row = QHBoxLayout()
        scoring_btn = QPushButton("Restore default scoring values")
        scoring_btn.setObjectName("rerun")
        scoring_btn.clicked.connect(lambda: self._restore_defaults("scoring"))
        restore_row.addWidget(scoring_btn)
        detection_btn = QPushButton("Restore default detection rules")
        detection_btn.setObjectName("rerun")
        detection_btn.clicked.connect(lambda: self._restore_defaults("detection"))
        restore_row.addWidget(detection_btn)
        restore_row.addStretch()
        restore_layout.addLayout(restore_row)
        layout.addWidget(restore_card)

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
        browse.setObjectName("browse")   # compact padding so the label fits
        # 70px clipped "Browse" to "rows"; size to the label plus padding.
        browse.setFixedWidth(90)
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
        """No-op: colours come from the app stylesheet. Kept for callers."""
        self._palette = palette

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Save only. Scoring/detection changes apply on the next launch."""
        result = self._perform_save()
        if result is None:
            return
        QMessageBox.information(
            self, "Saved",
            "Settings saved.\n\nScoring and detection changes are read when the "
            "pipeline runs, so restart CyberMon for them to take effect."
        )

    def _perform_save(self):
        """Validate, then write config atomically.

        Returns (before_cfg, after_cfg) on success, or None if validation or
        the write failed (in which case the user has already been told and
        nothing was written).
        """
        try:
            cfg = config_io.load_config(self._config_path)
        except config_io.ConfigError as exc:
            QMessageBox.warning(self, "Settings", str(exc))
            return None

        import copy
        before = copy.deepcopy(cfg)

        errors: list[str] = []

        # --- list fields: sanitise (control chars, length, duplicates, count) ---
        def _parse_list(field: QPlainTextEdit) -> list[str]:
            raw = field.toPlainText().replace("\n", ",")
            return [item for item in raw.split(",")]

        lists = {}
        for key, field, label in (
            ("high_impact_users", self._high_users_input, "High-impact users"),
            ("high_impact_resources", self._high_resources_input, "High-impact resources"),
            ("med_impact_resources", self._med_resources_input, "Medium-impact resources"),
        ):
            entries, errs = config_io.sanitise_entries(_parse_list(field), label)
            lists[key] = entries
            errors += errs

        # --- severity tiers: contiguous, non-overlapping, covering 1-25 ---
        tiers = {
            name: {"min": boxes["min"].value(), "max": boxes["max"].value()}
            for name, boxes in self._tier_inputs.items()
        }
        errors += config_io.validate_tiers(tiers)

        # --- numeric score values (range enforced here, not just in the widget) ---
        scores = {key: box.value() for key, box in self._score_inputs.items()}
        for key, value in scores.items():
            errors += config_io.validate_score(value, key)

        if errors:
            # Nothing is written when validation fails.
            self._show_errors(errors)
            return None

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

        cfg.setdefault("scoring", {})
        cfg["scoring"].setdefault("rules", {})
        cfg["scoring"]["rules"].update(lists)
        cfg["scoring"]["rules"].update(scores)
        cfg["scoring"]["severity_tiers"] = tiers

        # Theme preference is NOT written here: it is a UI setting persisted
        # to QSettings by theme.apply_theme(). config.yaml holds detection rules.
        new_theme_name = self._theme_combo.currentText().lower()

        # server.api_key and every other untouched key round-trip unchanged.
        try:
            config_io.write_config_atomic(cfg, self._config_path)
        except config_io.ConfigError as exc:
            QMessageBox.warning(self, "Settings", str(exc))
            return None

        _theme.set_active(new_theme_name)
        self.theme_changed.emit(new_theme_name)
        return before, cfg

    # Detection settings that a scores-only re-score cannot apply: they change
    # WHICH violations exist, which only a full pipeline run at startup can do.
    _DETECTION_KEYS = ("auth_log_path", "web_log_path", "detection")

    def _detection_changed(self, before: dict, after: dict) -> bool:
        return any(before.get(k) != after.get(k) for k in self._DETECTION_KEYS)

    def _save_and_rescore(self) -> None:
        """Save, then recompute scores for violations already in the database.

        Only risk_scores values are rewritten — events and violations rows are
        left exactly as they are. Detection changes still need a restart.
        """
        if self._rescoring:
            return                      # re-entrancy guard
        self._rescoring = True
        self._set_busy(True)
        try:
            result = self._perform_save()
            if result is None:
                return                  # validation/write failed; nothing re-scored
            before, after = result

            # Re-read from disk rather than trusting the in-memory dict.
            try:
                saved = config_io.load_config(self._config_path)
            except config_io.ConfigError as exc:
                QMessageBox.warning(self, "Settings", str(exc))
                return

            db_path = saved.get("storage", {}).get("db_path", "data/cybermon.db")
            try:
                summary = rescore_violations(db_path, saved)
            except Exception:
                # Full detail to the log; short, path-free message to the user.
                logger.exception("settings: re-score failed")
                QMessageBox.warning(
                    self, "Re-score failed",
                    "Settings were saved, but scores could not be recalculated.\n\n"
                    "Existing scores are unchanged. Restart CyberMon to rebuild "
                    "them from your log files."
                )
                return

            self.rescored.emit()        # MainWindow refreshes the data panels

            message = (
                f"Settings saved and {summary['total']} violation(s) re-scored "
                f"({summary['changed']} changed).\n\nNo restart needed for "
                f"scoring changes."
            )
            if self._detection_changed(before, after):
                message += (
                    "\n\nNote: you also changed detection settings (log paths, "
                    "thresholds, business hours or restricted resources). Those "
                    "decide which violations are found, so they only take effect "
                    "after restarting CyberMon."
                )
            QMessageBox.information(self, "Saved & re-scored", message)
        finally:
            self._rescoring = False
            self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        """Disable the action buttons while a re-score runs."""
        for btn in (self._save_btn, self._rescore_btn):
            btn.setEnabled(not busy)
        self._rescore_btn.setText("Re-scoring..." if busy else "Save && Re-score")
        QApplication.processEvents()    # let the disabled state paint

    def _show_errors(self, errors: list) -> None:
        """Surface validation problems without writing anything."""
        shown = "\n".join(f"• {e}" for e in errors[:10])
        if len(errors) > 10:
            shown += f"\n• ...and {len(errors) - 10} more."
        QMessageBox.warning(
            self, "Settings not saved",
            "Please correct the following before saving:\n\n" + shown,
        )

    def _restore_defaults(self, section: str) -> None:
        """Reset ONLY the named section from config_default.yaml.

        Log paths, setup_complete, mode, theme, server (incl. api_key), agent
        and storage are never touched.
        """
        labels = {
            "scoring": ("Restore default scoring values",
                        "This resets risk scoring values and severity tier "
                        "boundaries to their defaults.\n\nYour log file paths, "
                        "setup status, mode, theme and server settings are NOT "
                        "changed."),
            "detection": ("Restore default detection rules",
                          "This resets brute-force thresholds, restricted "
                          "resources and business hours to their defaults."
                          "\n\nYour log file paths, setup status, mode, theme "
                          "and server settings are NOT changed."),
        }
        title, body = labels[section]
        if QMessageBox.question(
            self, title, body + "\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return

        defaults_path = os.path.join(
            os.path.dirname(self._config_path) or ".", "config_default.yaml"
        )
        try:
            cfg = config_io.load_config(self._config_path)
            defaults = config_io.load_config(defaults_path)
            updated = config_io.restore_section(cfg, defaults, section)
            config_io.write_config_atomic(updated, self._config_path)
        except config_io.ConfigError as exc:
            QMessageBox.warning(self, "Settings", str(exc))
            return

        QMessageBox.information(
            self, title,
            "Defaults restored.\n\nRestart CyberMon for the changes to take effect."
        )

    def _reset_wizard(self) -> None:
        try:
            cfg = config_io.load_config(self._config_path)
            cfg["setup_complete"] = False
            config_io.write_config_atomic(cfg, self._config_path)
        except config_io.ConfigError as exc:
            QMessageBox.warning(self, "Settings", str(exc))
            return

        QMessageBox.information(
            self,
            "Wizard Reset",
            "The setup wizard will run the next time CyberMon is launched.",
        )
