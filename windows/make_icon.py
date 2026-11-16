"""Gera zekflix.png e zekflix.ico (usado pelo build do Windows)."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import (QGuiApplication, QPixmap, QPainter, QColor, QFont,
                         QPainterPath, QLinearGradient, QPolygonF)
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
z = QPolygonF([QPointF(x, y) for x, y in
               [(62, 58), (194, 58), (194, 86), (112, 170), (194, 170), (194, 198),
                (62, 198), (62, 170), (144, 86), (62, 86)]])
p.setPen(Qt.PenStyle.NoPen)
p.setBrush(QColor("#E50914"))
p.drawPolygon(z)
p.end()
assert pm.save("zekflix.png")
Image.open("zekflix.png").save(
    "zekflix.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icone gerado")
