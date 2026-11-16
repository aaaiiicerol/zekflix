"""Gera zekflix.png e zekflix.ico (usado pelo build do Windows)."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import (QGuiApplication, QPixmap, QPainter, QColor, QFont,
                         QPainterPath, QLinearGradient)
from PIL import Image

app = QGuiApplication([])
S = 256
pm = QPixmap(S, S)
pm.fill(Qt.GlobalColor.transparent)
p = QPainter(pm)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
path = QPainterPath()
path.addRoundedRect(QRectF(8, 8, S - 16, S - 16), 48, 48)
g = QLinearGradient(0, 0, S, S)
g.setColorAt(0, QColor("#2a2a2a"))
g.setColorAt(1, QColor("#0d0d0d"))
p.fillPath(path, g)
f = QFont("Segoe UI")
f.setBold(True)
f.setPixelSize(190)
p.setFont(f)
p.setPen(QColor("#E50914"))
p.drawText(QRectF(0, 0, S, S - 6), int(Qt.AlignmentFlag.AlignCenter), "Z")
p.end()
assert pm.save("zekflix.png")
Image.open("zekflix.png").save(
    "zekflix.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icone gerado")
