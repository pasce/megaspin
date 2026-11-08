"""Dark theme (Desktop_App_Design §11)."""
from __future__ import annotations

COLORS = {
    "bg": "#121212", "panel": "#181818", "card": "#1F1F1F", "hover": "#2A2A2A", "border": "#2C2C2C",
    "text": "#EDEDED", "text2": "#9A9A9A", "ok": "#4CAF50", "warn": "#F5A623", "err": "#E53935",
}


def stylesheet(accent: str = "#E04848") -> str:
    c = COLORS
    return f"""
* {{ font-family: "Segoe UI", "Noto Sans", "Inter", sans-serif; font-size: 13px; color: {c['text']}; }}
QMainWindow, QDialog {{ background: {c['bg']}; }}
QWidget#Central {{ background: {c['bg']}; }}
QWidget#Header {{ background: {c['panel']}; border-bottom: 1px solid {c['border']}; }}
QWidget#PlayerBar {{ background: {c['panel']}; border-top: 1px solid {c['border']}; }}
QLabel#Title {{ font-size: 15px; font-weight: 600; }}
QLabel#Subtitle, QLabel.secondary {{ color: {c['text2']}; font-size: 12px; }}
QLabel#AppName {{ font-size: 16px; font-weight: 700; }}
QLabel#Big {{ font-size: 22px; font-weight: 700; }}
QFrame#Card {{ background: {c['card']}; border-radius: 10px; }}
QStatusBar {{ background: {c['panel']}; color: {c['text2']}; border-top: 1px solid {c['border']}; }}
QStatusBar QLabel {{ color: {c['text2']}; padding: 0 8px; }}
QToolButton {{ background: transparent; border: none; border-radius: 18px; padding: 6px; }}
QToolButton:hover {{ background: {c['hover']}; }}
QToolButton:pressed {{ background: #333; }}
QToolButton:checked {{ background: {c['hover']}; }}
QToolButton#PlayButton {{ background: {accent}; border-radius: 22px; padding: 10px; }}
QToolButton#PlayButton:hover {{ background: {accent}; }}
QPushButton {{ background: {c['hover']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ background: #333; }}
QPushButton:default, QPushButton#Primary {{ background: {accent}; border-color: {accent}; }}
QPushButton:disabled {{ color: {c['text2']}; }}
QSpinBox, QLineEdit, QComboBox {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 5px 8px; }}
QSpinBox:focus, QLineEdit:focus, QComboBox:focus {{ border-color: {accent}; }}
QComboBox {{ combobox-popup: 0; }}
QComboBox QAbstractItemView {{ background: {c['card']}; border: 1px solid {c['border']}; outline: 0;
    selection-background-color: {accent}; padding: 2px; }}
QListWidget {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 6px; }}
QListWidget::item {{ padding: 6px; }}
QListWidget::item:selected {{ background: {accent}; }}
QProgressBar {{ background: {c['hover']}; border: none; border-radius: 2px; height: 4px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 2px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; }}
QToolTip {{ background: {c['card']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px; }}
QMenu {{ background: {c['card']}; border: 1px solid {c['border']}; }}
QMenu::item:selected {{ background: {accent}; }}
"""
