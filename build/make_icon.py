"""Generate assets/icon.ico using the QPainter shield from main_window.py.

Run from the project root:
    venv/Scripts/python build/make_icon.py
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QApplication

app = QApplication(sys.argv)

_PURPLE = "#7c3aed"

def _render(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(_PURPLE))
    p.setPen(Qt.PenStyle.NoPen)
    s = size
    path = QPainterPath()
    path.moveTo(s * 0.5,  s * 0.03)
    path.lineTo(s * 0.94, s * 0.22)
    path.lineTo(s * 0.94, s * 0.56)
    path.quadTo(s * 0.94, s * 0.875, s * 0.5, s * 0.97)
    path.quadTo(s * 0.06, s * 0.875, s * 0.06, s * 0.56)
    path.lineTo(s * 0.06, s * 0.22)
    path.closeSubpath()
    p.drawPath(path)
    p.setBrush(QColor("#ffffff"))
    rx = s * 0.34
    ry = s * 0.50
    rw = s * 0.31
    rh = s * 0.25
    p.drawRoundedRect(int(rx), int(ry), int(rw), int(rh), s * 0.06, s * 0.06)
    p.end()
    return pm


def _pixmap_to_pil(pm: QPixmap):
    from PIL import Image
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    buf.close()
    return Image.open(io.BytesIO(buf.data().data())).copy()


sizes = [16, 32, 48, 256]
pil_images = [_pixmap_to_pil(_render(s)) for s in sizes]

assets_dir = os.path.join(ROOT, "assets")
ico_path = os.path.join(assets_dir, "icon.ico")

pil_images[0].save(
    ico_path,
    format="ICO",
    sizes=[(s, s) for s in sizes],
    append_images=pil_images[1:],
)
print(f"[make_icon] Written {ico_path}")
