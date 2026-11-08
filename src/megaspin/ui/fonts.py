"""Font helpers (the stylesheet sets sizes in px, so pointSize may be -1)."""
from PySide6.QtGui import QFont


def scaled(font: QFont, factor: float, bold: bool | None = None) -> QFont:
    f = QFont(font)
    if f.pixelSize() > 0:
        f.setPixelSize(max(8, round(f.pixelSize() * factor)))
    elif f.pointSizeF() > 0:
        f.setPointSizeF(f.pointSizeF() * factor)
    if bold is not None:
        f.setBold(bold)
    return f


def sized_px(font: QFont, px: int, bold: bool | None = None) -> QFont:
    f = QFont(font)
    f.setPixelSize(px)
    if bold is not None:
        f.setBold(bold)
    return f
