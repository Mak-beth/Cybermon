"""Dev-mode taskbar identity and application icon (main.py).

Windows groups taskbar buttons by AppUserModelID, and a script run inherits
python.exe's identity and icon. main() sets an explicit ID in dev mode only
(never in the packaged exe), and sets assets/icon.ico as the app-wide icon.
"""
import ctypes
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

import main as cybermon_main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ID = "CyberMon.SecurityMonitoring.1"


def _fake_shell32(monkeypatch, hresult=0):
    shell32 = MagicMock()
    shell32.SetCurrentProcessExplicitAppUserModelID.return_value = hresult
    monkeypatch.setattr(ctypes, "windll", MagicMock(shell32=shell32), raising=False)
    return shell32.SetCurrentProcessExplicitAppUserModelID


# ---------------------------------------------------------------------------
# _set_windows_app_id
# ---------------------------------------------------------------------------

def test_app_id_set_in_windows_dev_mode(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    set_id = _fake_shell32(monkeypatch)

    cybermon_main._set_windows_app_id()

    set_id.assert_called_once_with(APP_ID)


def test_app_id_not_set_in_packaged_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    set_id = _fake_shell32(monkeypatch)

    cybermon_main._set_windows_app_id()

    set_id.assert_not_called()


def test_app_id_is_a_no_op_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    set_id = _fake_shell32(monkeypatch)

    cybermon_main._set_windows_app_id()

    set_id.assert_not_called()


def test_failed_hresult_is_logged_not_raised(monkeypatch, caplog):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    _fake_shell32(monkeypatch, hresult=-2147024809)      # E_INVALIDARG

    with caplog.at_level("ERROR"):
        cybermon_main._set_windows_app_id()               # must not raise

    assert "SetCurrentProcessExplicitAppUserModelID failed" in caplog.text


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows taskbar API")
def test_real_windows_api_reports_the_app_id():
    """In a fresh process: no explicit ID before, CyberMon's ID after."""
    code = (
        "import ctypes, main\n"
        "def current():\n"
        "    p = ctypes.c_wchar_p()\n"
        "    hr = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(p))\n"
        "    return hr, p.value\n"
        "print('BEFORE', *current())\n"
        "main._set_windows_app_id()\n"
        "print('AFTER', *current())\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    lines = dict(line.split(" ", 1) for line in out.stdout.splitlines()
                 if line.startswith(("BEFORE", "AFTER")))
    before_hr = int(lines["BEFORE"].split(" ", 1)[0])
    assert before_hr != 0, "a plain python process should have no explicit AppUserModelID"
    assert lines["AFTER"] == f"0 {APP_ID}"


# ---------------------------------------------------------------------------
# _apply_app_icon
# ---------------------------------------------------------------------------

def test_app_icon_loaded_from_assets_icon_ico(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    icon_path = cybermon_main._resource_path("assets/icon.ico")
    assert os.path.isfile(icon_path)
    app = MagicMock()

    with patch("PyQt6.QtGui.QIcon") as qicon:
        cybermon_main._apply_app_icon(app)

    qicon.assert_called_once_with(icon_path)
    app.setWindowIcon.assert_called_once_with(qicon.return_value)


def test_app_icon_skipped_when_asset_not_bundled(monkeypatch, tmp_path):
    """Packaged exe: icon.ico is the exe's embedded resource, not a data file."""
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    app = MagicMock()

    cybermon_main._apply_app_icon(app)

    app.setWindowIcon.assert_not_called()


# ---------------------------------------------------------------------------
# main() ordering
# ---------------------------------------------------------------------------

def test_main_sets_app_id_before_qapplication_then_applies_icon(tmp_path):
    from PyQt6 import QtWidgets
    from tests.test_run_on_launch import _run_main

    seen = {}

    def record_app_id():
        # Inside _run_main, QApplication is a mock: .called shows whether it was
        # constructed yet.
        seen["qapplication_already_created"] = QtWidgets.QApplication.called

    with patch.object(cybermon_main, "_set_windows_app_id", side_effect=record_app_id) as app_id, \
         patch.object(cybermon_main, "_apply_app_icon") as app_icon:
        _run_main(tmp_path, {"run_on_launch": False})

    app_id.assert_called_once_with()
    assert seen["qapplication_already_created"] is False
    app_icon.assert_called_once()


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

def test_run_main_harness_leaves_gui_modules_with_real_qt_classes():
    """Regression: a GUI module first imported while _run_main's QApplication
    and QIcon patches are active keeps the mocks for the whole session, so every
    later real MainWindow breaks. Checked in a fresh process, where no other
    test has imported main_window first."""
    code = (
        "import os, pathlib, tempfile\n"
        "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')\n"
        "import tests.test_run_on_launch as t\n"
        "t._run_main(pathlib.Path(tempfile.mkdtemp()), {'run_on_launch': False})\n"
        "import src.gui.main_window as mw\n"
        "from PyQt6 import QtGui, QtWidgets\n"
        "print('RESULT', mw.QApplication is QtWidgets.QApplication, mw.QIcon is QtGui.QIcon)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    result = [line for line in out.stdout.splitlines() if line.startswith("RESULT")]
    assert result == ["RESULT True True"]
