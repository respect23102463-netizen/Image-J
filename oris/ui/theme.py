"""Colours, stylesheet and programmatically drawn icons."""
from __future__ import annotations

import math
import os
import tempfile

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

THEMES = {
    "dark": dict(bg="#0c1210", panel="#121a17", panel2="#18231f", border="#25352e", text="#dce7e1",
                 muted="#86998f", accent="#2bb673", accent2="#17734a", sel="#1c4a36", canvas="#070a09",
                 plot="#0f1613", grid="#1f2c26", ontext="#06120c"),
    "light": dict(bg="#f3f6f4", panel="#ffffff", panel2="#e9efeb", border="#c9d5ce", text="#15201b",
                  muted="#5d6f66", accent="#17835a", accent2="#0f5c40", sel="#cde8da", canvas="#dde4e0",
                  plot="#ffffff", grid="#e2e9e5", ontext="#ffffff"),
}
C = dict(THEMES["light"])
CATEGORY_COLORS = ["#ffd400", "#ff5d5d", "#4fc3f7", "#7ee081", "#ff9f43", "#c792ea", "#f78fb3", "#ffffff"]

QSS = """
* { font-size: 13px; }
QWidget { background: @bg; color: @text; }
QMainWindow::separator { background: @border; width: 1px; height: 1px; }
QMenuBar { background: @panel; border-bottom: 1px solid @border; padding: 2px 4px; }
QMenuBar::item { padding: 5px 10px; border-radius: 4px; background: transparent; }
QMenuBar::item:selected { background: @sel; }
QMenu { background: @panel; border: 1px solid @border; padding: 4px; }
QMenu::item { padding: 5px 26px 5px 22px; border-radius: 4px; }
QMenu::item:selected { background: @sel; }
QMenu::item:disabled { color: @muted; }
QMenu::separator { height: 1px; background: @border; margin: 4px 6px; }
QToolBar { background: @panel; border: none; border-right: 1px solid @border; padding: 6px 4px; spacing: 4px; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 5px; }
QToolButton:hover { background: @panel2; }
QToolButton:checked { background: @sel; border-color: @accent; }
QDockWidget { titlebar-close-icon: none; }
QDockWidget::title { background: @panel; padding: 6px 8px; border-bottom: 1px solid @border; }
QTabWidget::pane { border: none; border-top: 1px solid @border; }
QTabBar::tab { background: transparent; color: @muted; padding: 7px 12px; border: none;
               border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: @text; border-bottom: 2px solid @accent; }
QTabBar::tab:hover { color: @text; }
QPushButton { background: @panel2; border: 1px solid @border; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { border-color: @accent; }
QPushButton:pressed { background: @sel; }
QPushButton:disabled { color: @muted; }
QPushButton[primary="true"] { background: @accent; color: @ontext; border-color: @accent; font-weight: 600; }
QPushButton[primary="true"]:hover { background: @accent2; color: #ffffff; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QListWidget, QTextBrowser {
    background: @panel; border: 1px solid @border; border-radius: 5px; padding: 4px 6px;
    selection-background-color: @accent2; selection-color: #ffffff; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: @accent; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow { image: url(@icons/down.png); width: 10px; height: 10px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right;
    width: 18px; border: none; background: transparent; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right;
    width: 18px; border: none; background: transparent; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(@icons/up.png); width: 8px; height: 8px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(@icons/down.png); width: 8px; height: 8px; }
QComboBox QAbstractItemView { background: @panel; border: 1px solid @border; selection-background-color: @sel;
                              selection-color: @text; }
QListWidget::item { padding: 3px 4px; border-radius: 3px; }
QListWidget::item:selected { background: @sel; color: @text; }
QTableView { background: @panel; alternate-background-color: @panel2; gridline-color: @border;
             border: none; selection-background-color: @sel; selection-color: @text; }
QHeaderView::section { background: @panel2; color: @text; border: none; border-right: 1px solid @border;
                       border-bottom: 1px solid @border; padding: 5px 8px; font-weight: 600; }
QTableCornerButton::section { background: @panel2; border: none; }
QGroupBox { border: 1px solid @border; border-radius: 8px; margin-top: 12px; padding: 10px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: @accent; font-weight: 600; }
QCheckBox, QLabel, QRadioButton { background: transparent; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid @border; border-radius: 3px; background: @panel; }
QCheckBox::indicator:checked { background: @accent; border-color: @accent; image: url(@icons/check.png); }
QMenu::indicator { width: 14px; height: 14px; left: 5px; }
QMenu::indicator:checked { image: url(@icons/check_menu.png); }
QTabBar::close-button { image: url(@icons/close.png); subcontrol-position: right; margin: 2px; }
QTabBar::close-button:hover { image: url(@icons/close_hover.png); }
QTabBar QToolButton { background: @panel; border: none; border-radius: 0; padding: 2px; }
QTabBar QToolButton::left-arrow { image: url(@icons/left.png); width: 10px; height: 10px; }
QTabBar QToolButton::right-arrow { image: url(@icons/right.png); width: 10px; height: 10px; }
QSlider::groove:horizontal { height: 4px; background: @border; border-radius: 2px; }
QSlider::handle:horizontal { background: @accent; width: 14px; margin: -5px 0; border-radius: 7px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle { background: @border; border-radius: 5px; min-height: 24px; min-width: 24px; }
QScrollBar::handle:hover { background: @muted; }
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page { background: none; border: none;
    width: 0; height: 0; }
QStatusBar { background: @panel; border-top: 1px solid @border; color: @muted; }
QStatusBar QLabel { color: @muted; padding: 0 8px; }
QProgressBar { background: @panel; border: 1px solid @border; border-radius: 5px; text-align: center; height: 16px; }
QProgressBar::chunk { background: @accent; border-radius: 4px; }
QToolTip { background: @panel2; color: @text; border: 1px solid @border; padding: 4px 6px; }
QScrollArea { border: none; }
QLabel[role="hint"] { color: @muted; }
QToolButton[role="module"] { border: none; border-bottom: 2px solid transparent; border-radius: 0; padding: 6px 2px 5px 2px;
    color: @muted; font-size: 12px; }
QToolButton[role="module"]:hover { color: @text; background: transparent; }
QToolButton[role="module"]:checked { color: @accent; border-bottom: 2px solid @accent; background: transparent; font-weight: 600; }
QWidget[role="modulebar"] { border-bottom: 1px solid @border; }
QToolButton[role="disclosure"] { color: @muted; border: none; padding: 4px 0; }
QToolButton[role="disclosure"]:hover { color: @text; background: transparent; }
QToolButton[role="disclosure"]:checked { background: transparent; color: @text; }
QLabel[role="big"] { font-size: 30px; font-weight: 700; color: @accent; }
QLabel[role="title"] { font-size: 22px; font-weight: 700; }
QSplitter::handle { background: @border; }
"""


def _write_icons(name):
    """Small arrow / check / close glyphs referenced from the stylesheet, drawn in the theme colours."""
    folder = os.path.join(tempfile.gettempdir(), "oris-icons", name)
    os.makedirs(folder, exist_ok=True)

    def make(fname, color, draw, size=16):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(color), 2.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        draw(p, float(size))
        p.end()
        pm.save(os.path.join(folder, fname))

    def chevron(pts):
        return lambda p, s: p.drawPolyline(QPolygonF([QPointF(x * s, y * s) for x, y in pts]))

    def cross(p, s):
        p.drawLine(QPointF(.3 * s, .3 * s), QPointF(.7 * s, .7 * s))
        p.drawLine(QPointF(.7 * s, .3 * s), QPointF(.3 * s, .7 * s))

    make("down.png", C["muted"], chevron([(.22, .36), (.5, .66), (.78, .36)]))
    make("up.png", C["muted"], chevron([(.22, .64), (.5, .34), (.78, .64)]))
    make("left.png", C["muted"], chevron([(.62, .22), (.34, .5), (.62, .78)]))
    make("right.png", C["muted"], chevron([(.38, .22), (.66, .5), (.38, .78)]))
    make("check.png", C["ontext"], chevron([(.2, .52), (.42, .74), (.8, .28)]))
    make("check_menu.png", C["accent"], chevron([(.2, .52), (.42, .74), (.8, .28)]))
    make("close.png", C["muted"], cross)
    make("close_hover.png", C["text"], cross)
    return folder.replace(os.sep, "/")


def stylesheet(icons=""):
    s = QSS.replace("@icons", icons)
    for k in sorted(C, key=len, reverse=True):
        s = s.replace("@" + k, C[k])
    return s


def apply_theme(app, name):
    C.clear()
    C.update(THEMES.get(name, THEMES["dark"]))
    app.setStyleSheet(stylesheet(_write_icons(name if name in THEMES else "dark")))


def tool_icon(name, size=26):
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(C["text"]), 1.7)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    s = float(size)
    m = s * 0.2
    if name == "rect":
        p.drawRect(QRectF(m, m * 1.3, s - 2 * m, s - 2.6 * m))
    elif name == "ellipse":
        p.drawEllipse(QRectF(m, m * 1.3, s - 2 * m, s - 2.6 * m))
    elif name == "polygon":
        pts = [(.5, .15), (.86, .42), (.72, .85), (.25, .8), (.14, .4)]
        p.drawPolygon(QPolygonF([QPointF(x * s, y * s) for x, y in pts]))
    elif name == "freehand":
        path = QPainterPath(QPointF(.2 * s, .55 * s))
        path.cubicTo(.1 * s, .1 * s, .55 * s, .1 * s, .55 * s, .4 * s)
        path.cubicTo(.55 * s, .6 * s, .95 * s, .35 * s, .82 * s, .7 * s)
        path.cubicTo(.7 * s, .95 * s, .3 * s, .9 * s, .2 * s, .55 * s)
        p.drawPath(path)
    elif name == "line":
        p.drawLine(QPointF(.2 * s, .8 * s), QPointF(.8 * s, .2 * s))
        p.setBrush(QColor(C["text"]))
        p.drawEllipse(QPointF(.2 * s, .8 * s), 1.8, 1.8)
        p.drawEllipse(QPointF(.8 * s, .2 * s), 1.8, 1.8)
    elif name == "point":
        c = s / 2
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p.drawLine(QPointF(c + dx * .16 * s, c + dy * .16 * s), QPointF(c + dx * .36 * s, c + dy * .36 * s))
        p.setBrush(QColor(C["accent"]))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(c, c), 2.4, 2.4)
    elif name == "wand":
        p.drawLine(QPointF(.2 * s, .82 * s), QPointF(.56 * s, .46 * s))
        p.setPen(QPen(QColor(C["accent"]), 1.6))
        cx, cy = .68 * s, .32 * s
        for i in range(4):
            a = i * math.pi / 4
            p.drawLine(QPointF(cx - math.cos(a) * .17 * s, cy - math.sin(a) * .17 * s),
                       QPointF(cx + math.cos(a) * .17 * s, cy + math.sin(a) * .17 * s))
    elif name == "hand":
        c = s / 2
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            tip = QPointF(c + dx * .36 * s, c + dy * .36 * s)
            p.drawLine(QPointF(c, c), tip)
            p.drawLine(tip, QPointF(tip.x() - dx * .12 * s + dy * .1 * s, tip.y() - dy * .12 * s + dx * .1 * s))
            p.drawLine(tip, QPointF(tip.x() - dx * .12 * s - dy * .1 * s, tip.y() - dy * .12 * s - dx * .1 * s))
    elif name == "zoom":
        p.drawEllipse(QPointF(.43 * s, .43 * s), .24 * s, .24 * s)
        p.drawLine(QPointF(.61 * s, .61 * s), QPointF(.84 * s, .84 * s))
    p.end()
    return QIcon(pm)


def module_icon(name, size=22, color=None):
    """Icons for the analysis module bar."""
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color or C["muted"]), 1.6)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    s = float(size)
    if name == "roi":
        p.drawRect(QRectF(.18 * s, .25 * s, .64 * s, .5 * s))
        for i in range(4):
            x = .3 * s + i * .13 * s
            p.drawLine(QPointF(x, .75 * s), QPointF(x, (.62 if i % 2 else .55) * s))
    elif name == "gel":
        p.drawRoundedRect(QRectF(.12 * s, .2 * s, .76 * s, .6 * s), 2, 2)
        pen.setWidthF(2.6)
        p.setPen(pen)
        for row in (.4, .62):
            for i in range(3):
                x = .24 * s + i * .2 * s
                p.drawLine(QPointF(x, row * s), QPointF(x + .1 * s, row * s))
    elif name == "cells":
        for cx, cy, r in ((.36, .4, .17), (.67, .36, .13), (.58, .68, .17)):
            p.drawEllipse(QPointF(cx * s, cy * s), r * s, r * s)
    elif name == "fluor":
        p.drawEllipse(QPointF(.4 * s, .5 * s), .24 * s, .24 * s)
        p.drawEllipse(QPointF(.6 * s, .5 * s), .24 * s, .24 * s)
    else:
        p.drawLine(QPointF(.18 * s, .18 * s), QPointF(.18 * s, .82 * s))
        p.drawLine(QPointF(.82 * s, .18 * s), QPointF(.82 * s, .82 * s))
        pen.setStyle(Qt.DotLine)
        p.setPen(pen)
        p.drawLine(QPointF(.38 * s, .18 * s), QPointF(.38 * s, .82 * s))
        p.drawLine(QPointF(.62 * s, .18 * s), QPointF(.62 * s, .82 * s))
    p.end()
    return QIcon(pm)


def app_icon():
    """A double helix on a deep green tile."""
    size = 256
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    from PySide6.QtGui import QLinearGradient
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#0f3d2b"))
    g.setColorAt(1, QColor("#050807"))
    p.setBrush(g)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(8, 8, size - 16, size - 16), 52, 52)
    n = 60
    a = [QPointF(128 + 46 * math.sin(i / n * 2 * math.pi), 44 + 168 * i / n) for i in range(n + 1)]
    b = [QPointF(128 - 46 * math.sin(i / n * 2 * math.pi), 44 + 168 * i / n) for i in range(n + 1)]
    p.setPen(QPen(QColor(255, 255, 255, 70), 5))
    for i in range(3, n, 6):
        p.drawLine(a[i], b[i])
    pen = QPen(QColor("#2bb673"), 13)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawPolyline(QPolygonF(a))
    pen.setColor(QColor("#e8f5ee"))
    p.setPen(pen)
    p.drawPolyline(QPolygonF(b))
    p.end()
    return QIcon(pm)
