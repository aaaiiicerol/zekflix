#!/usr/bin/env python3
"""ZekFlix - biblioteca local de filmes e séries estilo Netflix (Linux)."""
import os, sys, random, re, json, hashlib, shutil, subprocess, urllib.request, urllib.parse, urllib.error
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import (Qt, QRectF, QThread, QTimer, QVariantAnimation,
                          QPropertyAnimation, pyqtSignal)
from PyQt6.QtGui import (QPixmap, QPainter, QPainterPath, QColor, QFont,
                         QLinearGradient, QPen)
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QPushButton, QDialog, QFileDialog, QMessageBox,
                             QToolButton, QMenu, QInputDialog, QScrollArea,
                             QFrame)

OMDB_API_KEY = ""        # cada usuário informa a sua (fica em ~/.config/zekflix/config.json)


def set_api_key(k):
    global OMDB_API_KEY
    OMDB_API_KEY = (k or "").strip()


class OmdbError(Exception):
    """Problema com a chave ou com o limite diário do OMDb."""

CONFIG_DIR = Path.home() / ".config" / "zekflix"
CACHE_DIR = Path.home() / ".cache" / "zekflix"
POSTER_DIR = CACHE_DIR / "posters"
CONFIG_FILE = CONFIG_DIR / "config.json"
META_FILE = CACHE_DIR / "metadata.json"
for d in (CONFIG_DIR, CACHE_DIR, POSTER_DIR):
    d.mkdir(parents=True, exist_ok=True)

VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
             ".mpg", ".mpeg", ".ts", ".m2ts", ".3gp", ".ogv", ".divx", ".vob"}
RED, BG = "#E50914", "#141414"


# ----------------------------------------------------------------- utilidades
def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]


def parse_name(name):
    """'Matrix (1999) [1080p]' -> ('Matrix', '1999')"""
    s = re.sub(r"[._]", " ", name)
    s = re.sub(r"\[[^\]]*\]", " ", s)
    m = re.search(r"[\(\s]((?:19|20)\d{2})\)?(?:\s|$)", s + " ")
    year = m.group(1) if m else ""
    if m and m.start() > 0:
        s = s[:m.start()]
    s = re.sub(r"[\(\)]", " ", s)
    return re.sub(r"\s+", " ", s).strip() or name, year


@dataclass
class Media:
    name: str
    kind: str                       # "movie" | "series"
    files: list = field(default_factory=list)
    title: str = ""
    year: str = ""

    @property
    def key(self):
        return f"{self.kind}|{self.title.lower()}|{self.year}"


def scan_library(root: Path):
    items = []
    for entry in sorted(root.iterdir(), key=lambda p: natural_key(p.name)):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            vids = sorted((f for f in entry.rglob("*")
                           if f.is_file() and f.suffix.lower() in VIDEO_EXT),
                          key=lambda f: natural_key(f.relative_to(entry)))
            if not vids:
                continue
            kind = "movie" if len(vids) == 1 else "series"
            t, y = parse_name(entry.name)
            items.append(Media(entry.name, kind, [str(v) for v in vids], t, y))
        elif entry.suffix.lower() in VIDEO_EXT:           # vídeo solto = filme
            t, y = parse_name(entry.stem)
            items.append(Media(entry.stem, "movie", [str(entry)], t, y))
    return items


# ----------------------------------------------------------------------- OMDb
def omdb_request(**params):
    if not OMDB_API_KEY:
        raise OmdbError("Nenhuma chave do OMDb configurada.")
    params["apikey"] = OMDB_API_KEY
    url = "https://www.omdbapi.com/?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise OmdbError("Chave do OMDb inválida ou ainda não ativada "
                            "(confirme o e-mail que o OMDb enviou).")
        raise
    err = str(data.get("Error", ""))
    if data.get("Response") == "False":
        if "limit" in err.lower():
            raise OmdbError("O limite diário de consultas do OMDb foi atingido. "
                            "Tente novamente amanhã.")
        if "api key" in err.lower():
            raise OmdbError("Chave do OMDb inválida ou ainda não ativada "
                            "(confirme o e-mail que o OMDb enviou).")
    return data


def translate_pt(text):
    """Traduz EN -> PT-BR (endpoint gratuito do Google Translate)."""
    if not text or text == "N/A":
        return text
    parts, buf = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if buf and len(buf) + len(sent) > 800:
            parts.append(buf)
            buf = ""
        buf = (buf + " " + sent).strip()
    if buf:
        parts.append(buf)
    out = []
    for chunk in parts:
        body = urllib.parse.urlencode({"client": "gtx", "sl": "en", "tl": "pt",
                                       "dt": "t", "q": chunk}).encode()
        req = urllib.request.Request(
            "https://translate.googleapis.com/translate_a/single", data=body)
        with urllib.request.urlopen(req, timeout=15) as r:
            res = json.loads(r.read().decode("utf-8"))
        out.append("".join(seg[0] for seg in res[0] if seg[0]))
    return " ".join(out)


def add_translation(data):
    if data.get("notfound") or "PlotPT" in data:
        return data
    try:
        data["PlotPT"] = translate_pt(data.get("Plot", ""))
        data["GenrePT"] = translate_pt(data.get("Genre", ""))
    except Exception:
        pass                      # sem tradução agora: tenta de novo na próxima abertura
    return data


def fetch_metadata(m: Media):
    base = dict(t=m.title, type=m.kind, plot="full")
    data = omdb_request(**base, **({"y": m.year} if m.year else {}))
    if data.get("Response") != "True" and m.year:
        data = omdb_request(**base)
    if data.get("Response") != "True":
        return {"notfound": True}
    poster = data.get("Poster", "")
    if poster and poster != "N/A":
        dest = POSTER_DIR / (hashlib.md5(m.key.encode()).hexdigest() + ".jpg")
        try:
            urllib.request.urlretrieve(poster, dest)
            data["poster_file"] = str(dest)
        except Exception:
            pass
    return add_translation(data)


class MetaWorker(QThread):
    done = pyqtSignal(str, dict)
    error = pyqtSignal(str)

    def __init__(self, jobs, cache):
        super().__init__()
        self.jobs = jobs
        self.cache = cache

    def run(self):
        for m in self.jobs:
            if self.isInterruptionRequested():
                return
            try:
                old = self.cache.get(m.key)
                data = add_translation(dict(old)) if old else fetch_metadata(m)
                self.done.emit(m.key, data)
            except OmdbError as e:
                self.error.emit(str(e))
                return
            except Exception:
                continue            # erro de rede: não grava no cache, tenta depois


# --------------------------------------------------------------------- player
def play(files, start=0):
    files = files[start:]
    if shutil.which("mpv"):
        cmd = ["mpv", "--fs", "--save-position-on-quit", "--force-window=yes"] + files
    elif shutil.which("vlc"):
        cmd = ["vlc", "--fullscreen"] + files
    else:
        cmd = ["xdg-open", files[0]]
    env = os.environ.copy()
    if getattr(sys, "frozen", False):      # rodando empacotado (AppImage/PyInstaller)
        orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if orig is not None:
            env["LD_LIBRARY_PATH"] = orig
        else:
            env.pop("LD_LIBRARY_PATH", None)
        for var in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "PYTHONHOME",
                    "PYTHONPATH"):
            env.pop(var, None)
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env=env)
    except Exception as e:
        QMessageBox.warning(None, "ZekFlix", f"Não consegui abrir o player:\n{e}\n\n"
                            "Instale o mpv:  sudo apt install mpv")


# ------------------------------------------------------------------ visuais
PW, PH = 170, 255            # pôster em repouso
BW, BH = 186, 279            # pôster com zoom (hover)
CW, CH = 196, 292            # espaço de cada card
AA = QPainter.RenderHint.Antialiasing
SM = QPainter.RenderHint.SmoothPixmapTransform
COVER = Qt.AspectRatioMode.KeepAspectRatioByExpanding
SMOOTH = Qt.TransformationMode.SmoothTransformation
ALIGN_C = int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap)


def cover(pm, w, h):
    return pm.scaled(w, h, COVER, SMOOTH)


def blur_cover(pm, w, h):
    small = pm.scaled(40, 60, Qt.AspectRatioMode.IgnoreAspectRatio, SMOOTH)
    return cover(small, w, h)


def poster_pixmap(meta):
    pf = (meta or {}).get("poster_file")
    return QPixmap(pf) if pf and Path(pf).exists() else QPixmap()


def placeholder(title, w, h):
    pm = QPixmap(w, h)
    p = QPainter(pm)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor("#3b3b46"))
    g.setColorAt(1, QColor("#16161b"))
    p.fillRect(0, 0, w, h, g)
    f = QFont()
    f.setPixelSize(18)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#cfcfd6"))
    p.drawText(QRectF(14, 14, w - 28, h - 28), ALIGN_C, title)
    p.end()
    return pm


def rounded(pm, w, h, r):
    out = QPixmap(w, h)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHints(AA | SM)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), r, r)
    p.setClipPath(path)
    c = cover(pm, w, h)
    p.drawPixmap((w - c.width()) // 2, (h - c.height()) // 2, c)
    p.end()
    return out


def draw_shadow(p, r, radius, spread):
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(spread):
        p.setBrush(QColor(0, 0, 0, int(46 * (1 - i / spread) ** 2)))
        p.drawRoundedRect(r.adjusted(-i, -i + 4, i, i + 4), radius + i, radius + i)


def meta_line(meta):
    bits = [meta.get("Year"), meta.get("Rated"), meta.get("Runtime"),
            meta.get("GenrePT") or meta.get("Genre")]
    line = "  •  ".join(b for b in bits if b and b != "N/A")
    r = meta.get("imdbRating")
    if r and r != "N/A":
        line = f"<span style='color:#f5c518;font-weight:700'>★ {r}</span>  •  " + line
    return line


def plot_text(meta):
    t = meta.get("PlotPT") or meta.get("Plot")
    return t if t and t != "N/A" else "Sem descrição disponível."


class Card(QWidget):
    clicked = pyqtSignal(object)

    def __init__(self, media, meta):
        super().__init__()
        self.media = media
        self.t = 0.0
        self.setFixedSize(CW, CH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(150)
        self.anim.valueChanged.connect(self._tick)
        self.set_meta(meta)

    def set_meta(self, meta):
        self.meta = meta or {}
        src = poster_pixmap(self.meta)
        if src.isNull():
            src = placeholder(self.media.title, BW, BH)
        self.pm = rounded(src, BW, BH, 12)
        self.update()

    def _tick(self, v):
        self.t = float(v)
        self.update()

    def _go(self, end):
        self.anim.stop()
        self.anim.setStartValue(self.t)
        self.anim.setEndValue(end)
        self.anim.start()

    def enterEvent(self, e):
        self._go(1.0)

    def leaveEvent(self, e):
        self._go(0.0)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.media)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(AA | SM)
        s = self.t
        w, h = PW + (BW - PW) * s, PH + (BH - PH) * s
        r = QRectF((CW - w) / 2, (CH - h) / 2, w, h)
        draw_shadow(p, r, 12, 8 + int(8 * s))
        p.drawPixmap(r, self.pm, QRectF(self.pm.rect()))
        rating = self.meta.get("imdbRating")
        if rating and rating != "N/A":
            b = QRectF(r.right() - 56, r.top() + 8, 48, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 185))
            p.drawRoundedRect(b, 8, 8)
            f = QFont()
            f.setPixelSize(12)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#f5c518"))
            p.drawText(b, int(Qt.AlignmentFlag.AlignCenter), f"★ {rating}")
        if s > 0.01:
            p.save()
            p.setOpacity(s)
            clip = QPainterPath()
            clip.addRoundedRect(r, 12, 12)
            p.setClipPath(clip)
            g = QLinearGradient(0, r.bottom() - 130, 0, r.bottom())
            g.setColorAt(0, QColor(0, 0, 0, 0))
            g.setColorAt(1, QColor(0, 0, 0, 240))
            p.fillRect(QRectF(r.left(), r.bottom() - 130, r.width(), 130), g)
            f = QFont()
            f.setPixelSize(14)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("white"))
            title = self.meta.get("Title") or self.media.title
            p.drawText(QRectF(r.left() + 10, r.bottom() - 66, r.width() - 20, 42),
                       int(Qt.AlignmentFlag.AlignBottom) | int(Qt.TextFlag.TextWordWrap), title)
            f.setPixelSize(11)
            f.setBold(False)
            p.setFont(f)
            p.setPen(QColor("#b9b9c2"))
            year = self.meta.get("Year") or self.media.year
            kind = "Série" if self.media.kind == "series" else "Filme"
            p.drawText(QRectF(r.left() + 10, r.bottom() - 24, r.width() - 20, 18),
                       int(Qt.AlignmentFlag.AlignVCenter), f"{kind}  ·  {year}" if year else kind)
            p.setClipping(False)
            pen = QPen(QColor(255, 255, 255, 210))
            pen.setWidthF(2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 12, 12)
            p.restore()


class HScroll(QScrollArea):
    def wheelEvent(self, e):
        dx, dy = e.angleDelta().x(), e.angleDelta().y()
        if abs(dx) > abs(dy):
            sb = self.horizontalScrollBar()
            sb.setValue(sb.value() - dx)
            e.accept()
        else:
            e.ignore()


class Row(QWidget):
    def __init__(self, title, cards):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(56, 0, 48, 0)
        lab = QLabel(title)
        lab.setObjectName("row")
        head.addWidget(lab)
        head.addStretch(1)
        for txt, d in (("‹", -1), ("›", 1)):
            b = QToolButton()
            b.setText(txt)
            b.setObjectName("arrow")
            b.clicked.connect(lambda _, d=d: self.slide(d))
            head.addWidget(b)
        v.addLayout(head)
        self.sc = HScroll()
        self.sc.setFixedHeight(CH + 6)
        self.sc.setWidgetResizable(True)
        self.sc.setFrameShape(QFrame.Shape.NoFrame)
        self.sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sc.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sc.viewport().setAutoFillBackground(False)
        inner = QWidget()
        h = QHBoxLayout(inner)
        h.setContentsMargins(46, 0, 46, 0)
        h.setSpacing(0)
        for c in cards:
            h.addWidget(c)
        h.addStretch(1)
        self.sc.setWidget(inner)
        v.addWidget(self.sc)

    def slide(self, d):
        sb = self.sc.horizontalScrollBar()
        self._a = QPropertyAnimation(sb, b"value", self)
        self._a.setDuration(320)
        self._a.setEndValue(sb.value() + d * CW * 4)
        self._a.start()


class Grid(QWidget):
    def __init__(self, cards):
        super().__init__()
        self.cards = cards
        for c in cards:
            c.setParent(self)
            c.show()

    def relayout(self):
        cols = max(1, (self.width() - 92) // CW)
        for i, c in enumerate(self.cards):
            c.move(46 + (i % cols) * CW, (i // cols) * CH)
        self.setFixedHeight(((len(self.cards) + cols - 1) // cols) * CH + 10)

    def resizeEvent(self, e):
        self.relayout()


class Hero(QWidget):
    watch = pyqtSignal(object)
    info = pyqtSignal(object)

    def __init__(self, media, meta):
        super().__init__()
        self.media = media
        self.src = poster_pixmap(meta)
        self.big = rounded(self.src, 260, 390, 14) if not self.src.isNull() else None
        self._bg = None
        self.setFixedHeight(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(56, 0, 0, 0)
        box = QWidget()
        box.setFixedWidth(560)
        b = QVBoxLayout(box)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(12)
        tag = QLabel("● SÉRIE" if media.kind == "series" else "● FILME")
        tag.setObjectName("tag")
        title = QLabel(meta.get("Title") or media.title)
        title.setObjectName("herotitle")
        title.setWordWrap(True)
        sub = QLabel(meta_line(meta))
        sub.setObjectName("sub")
        txt = plot_text(meta)
        if len(txt) > 240:
            txt = txt[:240].rsplit(" ", 1)[0] + "…"
        plot = QLabel(txt)
        plot.setObjectName("plot")
        plot.setWordWrap(True)
        row = QHBoxLayout()
        row.setSpacing(12)
        bp = QPushButton("▶  Assistir")
        bp.setObjectName("play")
        bp.clicked.connect(lambda: self.watch.emit(self.media))
        bi = QPushButton("ⓘ  Mais informações")
        bi.setObjectName("info")
        bi.clicked.connect(lambda: self.info.emit(self.media))
        row.addWidget(bp)
        row.addWidget(bi)
        row.addStretch(1)
        for w in (tag, title, sub, plot):
            b.addWidget(w)
        b.addSpacing(6)
        b.addLayout(row)
        lay.addStretch(1)
        lay.addWidget(box)
        lay.addStretch(1)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(AA | SM)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor(BG))
        if not self.src.isNull():
            if not self._bg or self._bg[0] != (W, H):
                self._bg = ((W, H), blur_cover(self.src, W, H))
            c = self._bg[1]
            p.drawPixmap((W - c.width()) // 2, (H - c.height()) // 2, c)
        g = QLinearGradient(0, 0, W, 0)
        g.setColorAt(0, QColor(20, 20, 20, 250))
        g.setColorAt(0.55, QColor(20, 20, 20, 175))
        g.setColorAt(1, QColor(20, 20, 20, 90))
        p.fillRect(0, 0, W, H, g)
        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0, QColor(20, 20, 20, 0))
        g.setColorAt(0.55, QColor(20, 20, 20, 0))
        g.setColorAt(1, QColor(20, 20, 20, 255))
        p.fillRect(0, 0, W, H, g)
        if self.big and W > 900:
            r = QRectF(W - 260 - 100, (H - 390) / 2 - 8, 260, 390)
            draw_shadow(p, r, 14, 20)
            p.drawPixmap(int(r.x()), int(r.y()), self.big)


class TopBar(QWidget):
    def paintEvent(self, e):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(0, 0, 0))
        g.setColorAt(1, QColor(20, 20, 20))
        p.fillRect(self.rect(), g)


class DetailDialog(QDialog):
    def __init__(self, media, meta, parent=None):
        super().__init__(parent)
        self.media = media
        self.src = poster_pixmap(meta)
        self.setWindowTitle(f"ZekFlix — {media.title}")
        self.resize(980, 600)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(44, 40, 44, 40)
        lay.setSpacing(38)
        poster = QLabel()
        poster.setPixmap(rounded(self.src if not self.src.isNull()
                                 else placeholder(media.title, 300, 450), 300, 450, 16))
        poster.setAlignment(Qt.AlignmentFlag.AlignTop)
        poster.setFixedWidth(300)
        lay.addWidget(poster)

        right = QVBoxLayout()
        right.setSpacing(12)
        tag = QLabel("● SÉRIE" if media.kind == "series" else "● FILME")
        tag.setObjectName("tag")
        title = QLabel(meta.get("Title") or media.title)
        title.setObjectName("h1")
        title.setWordWrap(True)
        sub = QLabel(meta_line(meta))
        sub.setObjectName("sub")
        desc = QLabel(plot_text(meta))
        desc.setObjectName("plot")
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignTop)
        for w in (tag, title, sub, desc):
            right.addWidget(w)
        extra = []
        if meta.get("Director") not in (None, "N/A"):
            extra.append(f"<b>Direção:</b> {meta['Director']}")
        if meta.get("Actors") not in (None, "N/A"):
            extra.append(f"<b>Elenco:</b> {meta['Actors']}")
        if extra:
            e = QLabel("<br>".join(extra))
            e.setWordWrap(True)
            e.setObjectName("sub")
            right.addWidget(e)
        self.eps = None
        if media.kind == "series":
            self.eps = QListWidget()
            for i, f in enumerate(media.files, 1):
                self.eps.addItem(f"{i:02d}   {Path(f).stem}")
            self.eps.setCurrentRow(0)
            self.eps.itemDoubleClicked.connect(lambda _: self.start())
            right.addWidget(self.eps, 1)
        else:
            right.addStretch(1)
        btn = QPushButton("▶  Assistir" if media.kind == "movie" else "▶  Assistir episódio")
        btn.setObjectName("play")
        btn.clicked.connect(self.start)
        right.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addLayout(right, 1)

    def paintEvent(self, e):
        p = QPainter(self)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor(BG))
        if not self.src.isNull():
            c = blur_cover(self.src, W, H)
            p.drawPixmap((W - c.width()) // 2, (H - c.height()) // 2, c)
        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0, QColor(20, 20, 20, 200))
        g.setColorAt(1, QColor(20, 20, 20, 250))
        p.fillRect(0, 0, W, H, g)

    def start(self):
        idx = self.eps.currentRow() if self.eps else 0
        play(self.media.files, max(idx, 0))


# ------------------------------------------------------------------ janela
STYLE = f"""
QWidget {{ color: #e5e5e5; font-size: 14px; }}
QWidget#root, QWidget#content {{ background: {BG}; }}
QScrollArea {{ background: transparent; border: none; }}
QLabel#logo {{ color: {RED}; font-size: 32px; font-weight: 900; letter-spacing: 5px; }}
QLabel#row {{ font-size: 21px; font-weight: 700; color: #f2f2f2; }}
QLabel#head {{ font-size: 28px; font-weight: 800; color: white; padding: 22px 0 6px 56px; }}
QLabel#empty {{ color: #808080; font-size: 18px; }}
QLabel#tag {{ color: {RED}; font-size: 13px; font-weight: 800; }}
QLabel#herotitle {{ font-size: 46px; font-weight: 900; color: white; }}
QLabel#h1 {{ font-size: 32px; font-weight: 800; color: white; }}
QLabel#sub {{ color: #b8b8b8; font-size: 15px; }}
QLabel#plot {{ color: #ececec; font-size: 16px; }}
QLabel#status {{ color: #6f6f6f; padding: 4px 56px; font-size: 12px; }}
QPushButton#nav {{ background: transparent; border: none; padding: 8px 14px; color: #b3b3b3; font-weight: 600; }}
QPushButton#nav:hover {{ color: white; }}
QPushButton#nav:checked {{ color: white; font-weight: 800; border-bottom: 3px solid {RED}; }}
QToolButton {{ background: transparent; border: none; color: #b3b3b3; font-size: 18px; padding: 4px 10px; border-radius: 6px; }}
QToolButton:hover {{ color: white; background: rgba(255,255,255,25); }}
QToolButton#arrow {{ font-size: 24px; padding: 0 10px; }}
QToolButton::menu-indicator {{ image: none; }}
QLineEdit {{ background: rgba(0,0,0,150); border: 1px solid #4a4a4a; border-radius: 18px; padding: 8px 16px; min-width: 240px; color: white; }}
QLineEdit:focus {{ border-color: white; }}
QPushButton#play {{ background: white; color: black; border: none; border-radius: 6px; padding: 11px 28px; font-size: 16px; font-weight: 800; }}
QPushButton#play:hover {{ background: #d4d4d4; }}
QPushButton#info {{ background: rgba(109,109,110,180); color: white; border: none; border-radius: 6px; padding: 11px 24px; font-size: 16px; font-weight: 700; }}
QPushButton#info:hover {{ background: rgba(109,109,110,120); }}
QDialog QListWidget {{ background: rgba(255,255,255,18); border: none; border-radius: 10px; padding: 4px; outline: none; }}
QDialog QListWidget::item {{ padding: 9px 10px; border-radius: 6px; }}
QDialog QListWidget::item:hover {{ background: rgba(255,255,255,25); }}
QDialog QListWidget::item:selected {{ background: {RED}; color: white; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #3d3d3d; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
"""


class ZekFlix(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ZekFlix")
        self.resize(1360, 860)
        self.cfg = load_json(CONFIG_FILE, {})
        set_api_key(self.cfg.get("omdb_key", ""))
        self.meta = load_json(META_FILE, {})
        self.items, self.worker, self.filter = [], None, "all"
        self.cards, self.dirty, self.hero_key = {}, False, None

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        bar = TopBar()
        bar.setFixedHeight(76)
        h = QHBoxLayout(bar)
        h.setContentsMargins(56, 0, 48, 0)
        logo = QLabel("ZEKFLIX")
        logo.setObjectName("logo")
        h.addWidget(logo)
        h.addSpacing(24)
        self.navs = {}
        for key, label in (("all", "Início"), ("movie", "Filmes"), ("series", "Séries")):
            b = QPushButton(label)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, k=key: self.set_filter(k))
            self.navs[key] = b
            h.addWidget(b)
        self.navs["all"].setChecked(True)
        h.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Buscar títulos…")
        self.search.textChanged.connect(self.refresh_view)
        h.addWidget(self.search)
        mb = QToolButton()
        mb.setText("⚙")
        mb.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        menu.addAction("Trocar pasta da biblioteca…", self.choose_folder)
        menu.addAction("Configurar chave do OMDb…", self.change_key)
        menu.addAction("Procurar novos conteúdos", self.rescan)
        menu.addAction("Limpar cache e baixar tudo de novo", self.clear_cache)
        mb.setMenu(menu)
        h.addWidget(mb)
        v.addWidget(bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        v.addWidget(self.scroll, 1)
        self.status = QLabel("")
        self.status.setObjectName("status")
        v.addWidget(self.status)

    # --- chave do OMDb
    def ensure_key(self):
        if not OMDB_API_KEY:
            self.ask_key()

    def ask_key(self):
        text, ok = QInputDialog.getText(
            self, "Chave do OMDb",
            "Para baixar capas e descrições, o ZekFlix usa uma chave GRATUITA do OMDb.\n\n"
            "1) Abra https://www.omdbapi.com/apikey.aspx\n"
            "2) Escolha FREE, informe seu e-mail e confirme o e-mail que eles enviam\n"
            "3) Cole a chave aqui:", text=OMDB_API_KEY)
        if ok and text.strip():
            self.cfg["omdb_key"] = text.strip()
            save_json(CONFIG_FILE, self.cfg)
            set_api_key(text)
            return True
        return False

    def change_key(self):
        if self.ask_key() and self.cfg.get("library"):
            self.rescan()

    def on_error(self, msg):
        self.status.setText(msg)
        QMessageBox.warning(self, "ZekFlix — OMDb",
                            msg + "\n\nUse ⚙ > Configurar chave do OMDb para corrigir.")

    # --- pasta
    def ensure_folder(self):
        p = self.cfg.get("library")
        if p and Path(p).is_dir():
            return True
        QMessageBox.information(self, "Bem-vindo ao ZekFlix",
                                "Escolha a pasta que contém as subpastas dos seus "
                                "filmes e séries.")
        return self.choose_folder()

    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Pasta da biblioteca ZekFlix",
                                             self.cfg.get("library", str(Path.home())))
        if not d:
            return False
        self.cfg["library"] = d
        save_json(CONFIG_FILE, self.cfg)
        self.rescan()
        return True

    # --- biblioteca
    def rescan(self):
        self.items = scan_library(Path(self.cfg["library"]))
        self.refresh_view()
        pending = [m for m in self.items if m.key not in self.meta or
                   (not self.meta[m.key].get("notfound")
                    and "PlotPT" not in self.meta[m.key])]
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait()
        if pending and not OMDB_API_KEY:
            self.status.setText("Sem chave do OMDb: abra ⚙ > Configurar chave "
                                "para baixar capas e descrições.")
            return
        if pending:
            self.status.setText(f"Buscando informações de {len(pending)} título(s) no OMDb…")
            self.worker = MetaWorker(pending, dict(self.meta))
            self.worker.done.connect(self.on_meta)
            self.worker.error.connect(self.on_error)
            self.worker.finished.connect(self.on_finished)
            self.worker.start()
        else:
            self.on_finished()

    def on_finished(self):
        self.status.setText(f"{len(self.items)} título(s) na biblioteca  •  "
                            f"{self.cfg.get('library', '')}")
        if self.dirty:
            self.dirty = False
            self.refresh_view()

    def on_meta(self, key, data):
        self.meta[key] = data
        save_json(META_FILE, self.meta)
        self.dirty = True
        for c in self.cards.get(key, []):
            c.set_meta(data)

    def clear_cache(self):
        if QMessageBox.question(self, "ZekFlix", "Apagar o cache e baixar tudo de novo?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.meta = {}
        save_json(META_FILE, self.meta)
        for f in POSTER_DIR.glob("*"):
            f.unlink(missing_ok=True)
        self.rescan()

    def set_filter(self, k):
        self.filter = k
        for kk, b in self.navs.items():
            b.setChecked(kk == k)
        self.refresh_view()

    # --- telas
    def rating(self, m):
        try:
            return float(self.meta.get(m.key, {}).get("imdbRating", 0))
        except (TypeError, ValueError):
            return 0.0

    def make_card(self, m):
        c = Card(m, self.meta.get(m.key))
        c.clicked.connect(self.open_item)
        self.cards.setdefault(m.key, []).append(c)
        return c

    def refresh_view(self):
        sb = self.scroll.verticalScrollBar()
        keep = sb.value()
        self.cards = {}
        content = QWidget()
        content.setObjectName("content")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 40)
        lay.setSpacing(22)
        q = self.search.text().strip().lower()
        items = [m for m in self.items if self.filter in ("all", m.kind) and q in m.title.lower()]
        if not items:
            msg = QLabel("Nenhum título encontrado." if self.items else "Sua biblioteca está vazia.")
            msg.setObjectName("empty")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addSpacing(80)
            lay.addWidget(msg)
            lay.addStretch(1)
        elif self.filter == "all" and not q:
            self.add_home(lay, items)
        else:
            name = f"Resultados para “{q}”" if q else \
                ("Filmes" if self.filter == "movie" else "Séries")
            head = QLabel(name)
            head.setObjectName("head")
            lay.addWidget(head)
            lay.addWidget(Grid([self.make_card(m) for m in items]))
            lay.addStretch(1)
        self.scroll.setWidget(content)
        QTimer.singleShot(0, lambda: sb.setValue(keep))

    def add_home(self, lay, items):
        cands = sorted((m for m in items if self.meta.get(m.key, {}).get("poster_file")),
                       key=self.rating, reverse=True)[:5]
        if cands:
            keys = [m.key for m in cands]
            if self.hero_key not in keys:
                self.hero_key = random.choice(keys)
            hm = next(m for m in cands if m.key == self.hero_key)
            hero = Hero(hm, self.meta[hm.key])
            hero.watch.connect(lambda m: play(m.files))
            hero.info.connect(self.open_item)
            lay.addWidget(hero)
        else:
            lay.addSpacing(10)
        top = [m for m in sorted(items, key=self.rating, reverse=True) if self.rating(m) > 0][:15]
        for name, group in (("Mais bem avaliados", top),
                            ("Filmes", [m for m in items if m.kind == "movie"]),
                            ("Séries", [m for m in items if m.kind == "series"])):
            if group:
                lay.addWidget(Row(name, [self.make_card(m) for m in group]))
        lay.addStretch(1)

    def open_item(self, m):
        DetailDialog(m, self.meta.get(m.key, {}), self).exec()

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(3000)
        super().closeEvent(e)


def take_prints(w):
    """python3 zekflix.py --prints  ->  salva 4 prints em ~/zekflix-prints"""
    out = Path.home() / "zekflix-prints"
    out.mkdir(exist_ok=True)

    def save(name, widget):
        widget.grab().save(str(out / name))
        print("salvo:", out / name)

    def s1():
        save("1-inicio.png", w)
        w.set_filter("movie")
        QTimer.singleShot(1200, s2)

    def s2():
        save("2-filmes.png", w)
        w.set_filter("series")
        QTimer.singleShot(1200, s3)

    def s3():
        save("3-series.png", w)
        m = next((m for m in w.items if m.kind == "series"), None) or \
            (w.items[0] if w.items else None)
        if not m:
            QApplication.quit()
            return
        d = DetailDialog(m, w.meta.get(m.key, {}), w)
        d.show()

        def s4():
            save("4-detalhes.png", d)
            d.close()
            QApplication.quit()
        QTimer.singleShot(1200, s4)

    s1()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ZekFlix")
    app.setStyleSheet(STYLE)
    w = ZekFlix()
    w.show()
    w.ensure_key()
    if not w.ensure_folder():
        sys.exit(0)
    if w.items == []:
        w.rescan()
    if "--prints" in sys.argv:
        QTimer.singleShot(7000, lambda: take_prints(w))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
