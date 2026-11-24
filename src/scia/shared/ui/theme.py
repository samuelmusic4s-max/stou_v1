from pathlib import Path
import sys
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QWidget


def _resolve_global_qss() -> Path:
    local = Path(__file__).resolve().parent / "styles.qss"
    if local.exists():
        return local
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "scia" / "shared" / "ui" / "styles.qss"
        if bundled.exists():
            return bundled
    return local


PALETTE = {
    "bg": "#0b0e16",
    "surface": "#111726",
    "elevated": "#182034",
    "border": "#222b42",
    "primary": "#4f7df3",
    "primary_hover": "#6b92f7",
    "primary_pressed": "#3d68d8",
    "primary_tint": "rgba(79, 125, 243, 0.15)",
    "primary_light": "#8fb0ff",
    "accent": "#e0b252",
    "warning": "#f2b84b",
    "success": "#4cc38a",
    "danger": "#f06a6a",
    "text": "#e8ebf4",
    "text_secondary": "#a7b1c6",
    "text_muted": "#7c879d",
}


GLOBAL_QSS = _resolve_global_qss()


def load_qss(path: Path) -> str:
    if not path.exists():
        return ""
    qss = path.read_text(encoding="utf-8")
    for key, value in PALETTE.items():
        qss = qss.replace(f"var(--{key})", value)
    return qss


def apply_global_theme(app: QApplication) -> None:
    app.setFont(QFont("Inter", 11))
    app.setStyleSheet(load_qss(GLOBAL_QSS))


def apply_slice_qss(widget: QWidget, slice_file: str | Path) -> None:
    slice_path = Path(slice_file).resolve()
    qss_path = slice_path.parent / "styles.qss"
    if not qss_path.exists():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            qss_path = (
                Path(meipass)
                / "scia"
                / "features"
                / slice_path.parent.name
                / "styles.qss"
            )
    qss = load_qss(qss_path)
    if qss:
        widget.setStyleSheet(qss)


def make_title_font(size: int = 24) -> QFont:
    font = QFont("Georgia", size)
    font.setBold(True)
    return font


def _tint_svg(path: str, color: str, size: int = 24) -> QPixmap:
    svg = QSvgRenderer(path)
    px = size * 2
    img = QPixmap(px, px)
    img.fill(Qt.GlobalColor.transparent)

    p = QPainter(img)
    svg.render(p, QRectF(0, 0, px, px))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(img.rect(), QColor(color))
    p.end()

    img.setDevicePixelRatio(2.0)
    return img


def make_icon(
    path: str, color: str = PALETTE["text"], active: str | None = None
) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_tint_svg(path, color), QIcon.Mode.Normal, QIcon.State.Off)
    if active:
        icon.addPixmap(_tint_svg(path, active), QIcon.Mode.Normal, QIcon.State.On)
    return icon
