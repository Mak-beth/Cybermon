"""Offscreen GUI smoke test — instantiates every panel to catch wiring errors.

Not part of the pytest suite (needs a Qt platform); run manually:
    venv/Scripts/python scripts/gui_smoke.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml

config = yaml.safe_load(open("config/config.yaml", encoding="utf-8"))

from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)

from src.gui.main_window import MainWindow

window = MainWindow(config)
window.show()
app.processEvents()

# Exercise every sidebar panel
for i in range(5):
    window._switch_to(i)
    app.processEvents()

# Exercise the settings save path without writing the real config:
# verify the new R11-C fields exist and parse correctly.
settings = window._panels[4]
assert hasattr(settings, "_high_users_input"), "R11-C high users field missing"
assert hasattr(settings, "_high_resources_input"), "R11-C high resources field missing"
assert hasattr(settings, "_med_resources_input"), "R11-C med resources field missing"

users_text = settings._high_users_input.toPlainText()
assert "root" in users_text and "admin" in users_text, f"unexpected: {users_text!r}"

# Theme switch both ways
window.apply_theme("dark")
app.processEvents()
window.apply_theme("light")
app.processEvents()

print("GUI smoke test PASSED — all 5 panels constructed, R11-C fields present, theme switch OK")
