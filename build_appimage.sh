#!/usr/bin/env bash
# Gera ZekFlix-x86_64.AppImage a partir do zekflix.py (rodar no Fedora, com internet).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

[ -f zekflix.py ] || { echo "zekflix.py precisa estar na mesma pasta deste script."; exit 1; }

echo "==> 1/5 Criando ambiente virtual e instalando PyQt6 + PyInstaller"
rm -rf build_tmp
mkdir build_tmp
python3 -m venv build_tmp/venv
# shellcheck disable=SC1091
. build_tmp/venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet PyQt6 pyinstaller certifi

echo "==> 2/5 Gerando o ícone"
QT_QPA_PLATFORM=offscreen python - <<'EOF'
from PyQt6.QtGui import (QGuiApplication, QPixmap, QPainter, QColor, QFont,
                         QPainterPath, QLinearGradient)
from PyQt6.QtCore import Qt, QRectF
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
f = QFont("Sans")
f.setBold(True)
f.setPixelSize(190)
p.setFont(f)
p.setPen(QColor("#E50914"))
p.drawText(QRectF(0, 0, S, S - 6), int(Qt.AlignmentFlag.AlignCenter), "Z")
p.end()
pm.save("build_tmp/zekflix.png")
EOF

echo "==> 3/5 Empacotando com PyInstaller (pode demorar alguns minutos)"
pyinstaller --noconfirm --windowed --name zekflix \
    --distpath build_tmp/dist --workpath build_tmp/work --specpath build_tmp \
    --add-data "$PWD/build_tmp/zekflix.png:." \
    zekflix.py

echo "==> 4/5 Montando o AppDir"
APPDIR=build_tmp/AppDir
mkdir -p "$APPDIR/usr/bin"
cp -r build_tmp/dist/zekflix/. "$APPDIR/usr/bin/"
cp build_tmp/zekflix.png "$APPDIR/zekflix.png"
cp build_tmp/zekflix.png "$APPDIR/.DirIcon"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/zekflix" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/zekflix.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=ZekFlix
Comment=Seus filmes e séries em um só lugar
Exec=zekflix
Icon=zekflix
Categories=AudioVideo;Video;Player;
Terminal=false
EOF

echo "==> 5/5 Gerando o AppImage"
if [ ! -x ./appimagetool ]; then
    curl -L --fail -o appimagetool \
      https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x appimagetool
fi
ARCH=x86_64 ./appimagetool --appimage-extract-and-run "$APPDIR" ZekFlix-x86_64.AppImage
chmod +x ZekFlix-x86_64.AppImage

echo
echo "Pronto! Arquivo gerado: $(pwd)/ZekFlix-x86_64.AppImage"
echo "Pode apagar a pasta build_tmp se quiser."
