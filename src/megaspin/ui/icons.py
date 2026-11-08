"""Monochrome SVG icons (own simple shapes), tinted at runtime."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_STROKE = 'fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
_FILL = 'fill="{c}"'

SVG = {
    "play": f'<path {_FILL} d="M8 5v14l11-7z"/>',
    "pause": f'<rect {_FILL} x="6" y="5" width="4" height="14" rx="1"/><rect {_FILL} x="14" y="5" width="4" height="14" rx="1"/>',
    "stop": f'<rect {_FILL} x="6" y="6" width="12" height="12" rx="1.5"/>',
    "next": f'<path {_FILL} d="M6 5v14l9-7z"/><rect {_FILL} x="16" y="5" width="2.5" height="14" rx="1"/>',
    "prev": f'<path {_FILL} d="M18 5v14l-9-7z"/><rect {_FILL} x="5.5" y="5" width="2.5" height="14" rx="1"/>',
    "ff": f'<path {_FILL} d="M3 6v12l8.5-6z M12.5 6v12l8.5-6z"/>',
    "rew": f'<path {_FILL} d="M21 6v12l-8.5-6z M11.5 6v12L3 12z"/>',
    "repeat": f'<g {_STROKE}><path d="M17 2l3 3-3 3"/><path d="M4 11V9a4 4 0 0 1 4-4h12"/>'
              f'<path d="M7 22l-3-3 3-3"/><path d="M20 13v2a4 4 0 0 1-4 4H4"/></g>',
    "shuffle": f'<g {_STROKE}><path d="M16 3h5v5"/><path d="M4 20L21 3"/><path d="M21 16v5h-5"/>'
               f'<path d="M15 15l6 6"/><path d="M4 4l5 5"/></g>',
    "disc": f'<g {_STROKE}><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/></g>',
    "plug": f'<g {_STROKE}><path d="M9 2v6M15 2v6"/><path d="M6 8h12v4a6 6 0 0 1-12 0z"/><path d="M12 18v4"/></g>',
    "settings": f'<g {_STROKE}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></g>',
    "menu": f'<g {_STROKE}><path d="M4 6h16M4 12h16M4 18h16"/></g>',
    "edit": f'<g {_STROKE}><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/></g>',
    "refresh": f'<g {_STROKE}><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></g>',
}


@lru_cache(maxsize=256)
def icon(name: str, color: str = "#EDEDED", size: int = 24) -> QIcon:
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{SVG[name].format(c=color)}</svg>'
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    ic = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        renderer.render(p, QRectF(0, 0, size * scale, size * scale))
        p.end()
        pm.setDevicePixelRatio(scale)
        ic.addPixmap(pm)
    return ic
