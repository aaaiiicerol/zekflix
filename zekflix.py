#!/usr/bin/env python3
"""ZekFlix - biblioteca local de filmes e séries estilo Netflix (Linux)."""
import sys, re, json, hashlib, shutil, subprocess, urllib.request, urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, QRectF, QThread, pyqtSignal
from PyQt6.QtGui import (QPixmap, QPainter, QPainterPath, QColor, QFont, QIcon,
                         QLinearGradient)
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QPushButton, QDialog, QFileDialog,
                             QMessageBox, QToolButton, QMenu, QListView)

OMDB_API_KEY = "c3fe24b2"

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
    params["apikey"] = OMDB_API_KEY
    url = "https://www.omdbapi.com/?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


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
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        QMessageBox.warning(None, "ZekFlix", f"Não consegui abrir o player:\n{e}\n\n"
                            "Instale o mpv:  sudo apt install mpv")


# ------------------------------------------------------------------ visuais
def make_card(poster_path, title, rating):
    W, H = 200, 300
    pm = QPixmap(W, H)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, W, H), 12, 12)
    p.setClipPath(path)
    src = QPixmap(poster_path) if poster_path and Path(poster_path).exists() else QPixmap()
    if src.isNull():
        g = QLinearGradient(0, 0, W, H)
        g.setColorAt(0, QColor("#3a3a3a"))
        g.setColorAt(1, QColor("#161616"))
        p.fillRect(0, 0, W, H, g)
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#bbbbbb"))
        p.drawText(QRectF(16, 16, W - 32, H - 32),
                   int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap), title)
    else:
        s = src.scaled(W, H, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)
        p.drawPixmap((W - s.width()) // 2, (H - s.height()) // 2, s)
    if rating and rating != "N/A":
        p.setClipping(False)
        p.setBrush(QColor(0, 0, 0, 190))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(W - 66, 8, 58, 24), 8, 8)
        f = QFont()
        f.setPointSize(10)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#f5c518"))
        p.drawText(QRectF(W - 66, 8, 58, 24), int(Qt.AlignmentFlag.AlignCenter), f"★ {rating}")
    p.end()
    return pm


class DetailDialog(QDialog):
    def __init__(self, media: Media, meta: dict, parent=None):
        super().__init__(parent)
        self.media = media
        self.setWindowTitle(f"ZekFlix — {media.title}")
        self.resize(900, 560)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 28)
        lay.setSpacing(28)

        poster = QLabel()
        pf = meta.get("poster_file")
        pm = QPixmap(pf) if pf and Path(pf).exists() else make_card(None, media.title, "")
        poster.setPixmap(pm.scaled(280, 420, Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation))
        poster.setAlignment(Qt.AlignmentFlag.AlignTop)
        lay.addWidget(poster)

        right = QVBoxLayout()
        right.setSpacing(10)
        title = QLabel(meta.get("Title") or media.title)
        title.setObjectName("h1")
        title.setWordWrap(True)
        right.addWidget(title)

        bits = [meta.get("Year"), meta.get("Rated"), meta.get("Runtime"),
                meta.get("GenrePT") or meta.get("Genre")]
        rating = meta.get("imdbRating")
        line = "  •  ".join(b for b in bits if b and b != "N/A")
        if rating and rating != "N/A":
            line = f"<span style='color:#f5c518'>★ {rating}</span>  •  " + line
        sub = QLabel(line)
        sub.setObjectName("sub")
        right.addWidget(sub)

        plot = meta.get("PlotPT") or meta.get("Plot")
        desc = QLabel(plot if plot and plot != "N/A" else "Sem descrição disponível.")
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignTop)
        right.addWidget(desc)

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
                self.eps.addItem(f"{i:02d}  ·  {Path(f).stem}")
            self.eps.setCurrentRow(0)
            self.eps.itemDoubleClicked.connect(lambda _: self.start())
            right.addWidget(self.eps, 1)
        else:
            right.addStretch(1)

        btn = QPushButton("▶  Assistir" if media.kind == "movie" else "▶  Assistir episódio selecionado")
        btn.setObjectName("play")
        btn.clicked.connect(self.start)
        right.addWidget(btn)
        lay.addLayout(right, 1)

    def start(self):
        idx = self.eps.currentRow() if self.eps else 0
        play(self.media.files, max(idx, 0))


# ------------------------------------------------------------------ janela
STYLE = f"""
QMainWindow, QDialog, QWidget#root {{ background: {BG}; }}
QWidget {{ color: #e5e5e5; font-size: 14px; }}
QLabel#logo {{ color: {RED}; font-size: 30px; font-weight: 900; letter-spacing: 4px; }}
QLabel#h1 {{ font-size: 30px; font-weight: 800; color: white; }}
QLabel#sub {{ color: #a3a3a3; }}
QLabel#status {{ color: #808080; padding: 4px 24px; }}
QPushButton.nav, QToolButton {{ background: transparent; border: none; padding: 8px 14px;
    color: #b3b3b3; font-weight: 600; border-radius: 6px; }}
QPushButton.nav:hover, QToolButton:hover {{ color: white; }}
QPushButton.nav:checked {{ color: white; background: #2a2a2a; }}
QToolButton::menu-indicator {{ image: none; }}
QLineEdit {{ background: #262626; border: 1px solid #3a3a3a; border-radius: 18px;
    padding: 8px 16px; min-width: 240px; color: white; }}
QLineEdit:focus {{ border-color: {RED}; }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ color: #d0d0d0; border-radius: 10px; padding: 6px; }}
QListWidget::item:hover {{ background: #232323; }}
QListWidget::item:selected {{ background: #2e2e2e; color: white; }}
QDialog QListWidget {{ background: #1c1c1c; border-radius: 8px; padding: 4px; }}
QDialog QListWidget::item {{ padding: 8px; }}
QDialog QListWidget::item:selected {{ background: {RED}; }}
QPushButton#play {{ background: {RED}; color: white; border: none; border-radius: 8px;
    padding: 12px 22px; font-size: 15px; font-weight: 700; }}
QPushButton#play:hover {{ background: #f6121d; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #3a3a3a; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


class ZekFlix(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ZekFlix")
        self.resize(1280, 800)
        self.cfg = load_json(CONFIG_FILE, {})
        self.meta = load_json(META_FILE, {})
        self.items, self.worker, self.filter = [], None, "all"

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(24, 14, 24, 8)

        bar = QHBoxLayout()
        logo = QLabel("ZEKFLIX")
        logo.setObjectName("logo")
        bar.addWidget(logo)
        bar.addSpacing(20)
        self.navs = {}
        for key, label in (("all", "Início"), ("movie", "Filmes"), ("series", "Séries")):
            b = QPushButton(label)
            b.setProperty("class", "nav")
            b.setCheckable(True)
            b.clicked.connect(lambda _, k=key: self.set_filter(k))
            self.navs[key] = b
            bar.addWidget(b)
        self.navs["all"].setChecked(True)
        bar.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Buscar títulos…")
        self.search.textChanged.connect(self.refresh_view)
        bar.addWidget(self.search)
        menu_btn = QToolButton()
        menu_btn.setText("⚙")
        menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        menu.addAction("Trocar pasta da biblioteca…", self.choose_folder)
        menu.addAction("Procurar novos conteúdos", self.rescan)
        menu.addAction("Limpar cache e baixar tudo de novo", self.clear_cache)
        menu_btn.setMenu(menu)
        bar.addWidget(menu_btn)
        v.addLayout(bar)

        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setIconSize(QSize(200, 300))
        self.list.setGridSize(QSize(224, 372))
        self.list.setWordWrap(True)
        self.list.setSpacing(6)
        self.list.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.list.itemActivated.connect(self.open_item)
        self.list.itemClicked.connect(self.open_item)
        v.addWidget(self.list, 1)

        self.status = QLabel("")
        self.status.setObjectName("status")
        v.addWidget(self.status)

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
        root = Path(self.cfg["library"])
        self.items = scan_library(root)
        self.refresh_view()
        pending = [m for m in self.items if m.key not in self.meta or
                   (not self.meta[m.key].get("notfound")
                    and "PlotPT" not in self.meta[m.key])]
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait()
        if pending:
            self.status.setText(f"Buscando informações de {len(pending)} título(s) no OMDb…")
            self.worker = MetaWorker(pending, dict(self.meta))
            self.worker.done.connect(self.on_meta)
            self.worker.finished.connect(self.on_finished)
            self.worker.start()
        else:
            self.on_finished()

    def on_finished(self):
        self.status.setText(f"{len(self.items)} título(s) na biblioteca  •  "
                            f"{self.cfg.get('library', '')}")

    def on_meta(self, key, data):
        self.meta[key] = data
        save_json(META_FILE, self.meta)
        for i in range(self.list.count()):
            it = self.list.item(i)
            m = it.data(Qt.ItemDataRole.UserRole)
            if m.key == key:
                self.style_item(it, m)

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

    def style_item(self, it, m):
        md = self.meta.get(m.key, {})
        shown = md.get("Title") or m.title
        year = md.get("Year", m.year)
        it.setText(f"{shown}" + (f"\n{year}" if year else ""))
        it.setIcon(QIcon(make_card(md.get("poster_file"), m.title, md.get("imdbRating"))))
        it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

    def refresh_view(self):
        q = self.search.text().strip().lower()
        self.list.clear()
        for m in self.items:
            if self.filter != "all" and m.kind != self.filter:
                continue
            if q and q not in m.title.lower():
                continue
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, m)
            it.setSizeHint(QSize(220, 368))
            self.style_item(it, m)
            self.list.addItem(it)

    def open_item(self, it):
        m = it.data(Qt.ItemDataRole.UserRole)
        DetailDialog(m, self.meta.get(m.key, {}), self).exec()

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(3000)
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ZekFlix")
    app.setStyleSheet(STYLE)
    w = ZekFlix()
    w.show()
    if not w.ensure_folder():
        sys.exit(0)
    if w.items == []:
        w.rescan()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
