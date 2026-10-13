"""A small dependency-free plotting widget (lines, bars, shaded spans, 2-D density)."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core.image import get_lut
from .theme import C


def nice_ticks(lo, hi, n=5):
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        return [lo]
    raw = (hi - lo) / max(n, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = min((1, 2, 2.5, 5, 10), key=lambda m: abs(m * mag - raw)) * mag
    first = math.ceil(lo / step - 1e-9) * step
    out = []
    v = first
    while v <= hi + step * 1e-6:
        out.append(0.0 if abs(v) < step * 1e-9 else v)
        v += step
    return out


def tick_label(v):
    a = abs(v)
    if a >= 1e5 or (0 < a < 1e-3):
        return f"{v:.1e}"
    return f"{v:.6g}"


class PlotWidget(QWidget):
    def __init__(self, parent=None, min_height=150):
        super().__init__(parent)
        self.setMinimumHeight(min_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.clear()

    def clear(self):
        self.series, self.spans, self.vlines = [], [], []
        self.image = None
        self.xlabel = self.ylabel = self.message = ""
        self.xrange = self.yrange = None
        self.logy = False
        self.update()

    def set_data(self, series=(), spans=(), vlines=(), image=None, xlabel="", ylabel="", xrange=None,
                 yrange=None, logy=False, message=""):
        """series: dicts with x, y and optional color, fill, bars, width.
        spans: (x0, x1, color). vlines: (x, color). image: 2-D array drawn over xrange x yrange."""
        self.series = [dict(s, x=np.asarray(s["x"], float), y=np.asarray(s["y"], float)) for s in series]
        self.spans, self.vlines, self.image = list(spans), list(vlines), image
        self.xlabel, self.ylabel, self.xrange, self.yrange = xlabel, ylabel, xrange, yrange
        self.logy, self.message = logy, message
        self.update()

    def _ranges(self):
        xs = [s["x"] for s in self.series if s["x"].size]
        ys = [self._y(s["y"]) for s in self.series if s["y"].size]
        xr = self.xrange or ((min(x.min() for x in xs), max(x.max() for x in xs)) if xs else (0, 1))
        yr = self.yrange or ((min(0.0, min(y.min() for y in ys)), max(y.max() for y in ys)) if ys else (0, 1))
        xr = (xr[0], xr[1] if xr[1] > xr[0] else xr[0] + 1)
        yr = (yr[0], yr[1] if yr[1] > yr[0] else yr[0] + 1)
        if self.image is None and self.yrange is None:
            yr = (yr[0], yr[1] + (yr[1] - yr[0]) * 0.06)
        return xr, yr

    def _y(self, y):
        return np.log10(np.maximum(y, 0) + 1) if self.logy else y

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(C["plot"]))
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1.5))
        p.setFont(font)
        L, R, Tm, B = 54, 12, 10, 24 + (14 if self.xlabel else 0)
        pw, ph = w - L - R, h - Tm - B
        if pw < 20 or ph < 20:
            return
        if not self.series and self.image is None:
            p.setPen(QColor(C["muted"]))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter | Qt.TextWordWrap, self.message)
            return
        (x0, x1), (y0, y1) = self._ranges()

        def mx(v):
            return L + (v - x0) / (x1 - x0) * pw

        def my(v):
            return Tm + ph - (v - y0) / (y1 - y0) * ph

        grid, muted = QColor(C["grid"]), QColor(C["muted"])
        for v in nice_ticks(x0, x1, max(2, pw // 80)):
            x = mx(v)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(x, Tm), QPointF(x, Tm + ph))
            p.setPen(muted)
            p.drawText(QRectF(x - 40, Tm + ph + 3, 80, 14), Qt.AlignHCenter | Qt.AlignTop, tick_label(v))
        for v in nice_ticks(y0, y1, max(2, ph // 40)):
            y = my(v)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(L, y), QPointF(L + pw, y))
            p.setPen(muted)
            lab = f"{10 ** v - 1:.3g}" if self.logy else tick_label(v)
            p.drawText(QRectF(0, y - 8, L - 5, 16), Qt.AlignRight | Qt.AlignVCenter, lab)
        if self.xlabel:
            p.setPen(muted)
            p.drawText(QRectF(L, h - 16, pw, 14), Qt.AlignCenter, self.xlabel)
        if self.ylabel:
            p.save()
            p.translate(11, Tm + ph / 2)
            p.rotate(-90)
            p.setPen(muted)
            p.drawText(QRectF(-ph / 2, -8, ph, 14), Qt.AlignCenter, self.ylabel)
            p.restore()
        p.setClipRect(QRectF(L, Tm, pw, ph))
        if self.image is not None:
            a = np.asarray(self.image, float)
            a = np.log1p(a)
            idx = (a / a.max() * 255).astype(np.uint8) if a.max() > 0 else a.astype(np.uint8)
            rgb = np.ascontiguousarray(get_lut("fire")[idx][::-1])
            img = QImage(rgb.data, rgb.shape[1], rgb.shape[0], 3 * rgb.shape[1], QImage.Format_RGB888)
            p.setRenderHint(QPainter.SmoothPixmapTransform, False)
            p.drawImage(QRectF(L, Tm, pw, ph), img)
        for a, b, col in self.spans:
            c = QColor(col)
            c.setAlpha(70)
            p.fillRect(QRectF(mx(a), Tm, max(1.0, mx(b) - mx(a)), ph), c)
        for s in self.series:
            x, y = s["x"], self._y(s["y"])
            if x.size == 0:
                continue
            col = QColor(s.get("color", C["accent"]))
            if x.size > 4 * pw and not s.get("bars"):
                step = int(math.ceil(x.size / (2 * pw)))
                x, y = x[::step], y[::step]
            if s.get("bars"):
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                bw = max(1.0, pw / x.size)
                base = my(max(y0, 0.0))
                for xv, yv in zip(x, y):
                    top = my(yv)
                    p.drawRect(QRectF(mx(xv), top, bw + 0.5, base - top))
                continue
            pts = [QPointF(mx(a), my(b)) for a, b in zip(x, y)]
            if s.get("fill"):
                fc = QColor(col)
                fc.setAlpha(60)
                p.setPen(Qt.NoPen)
                p.setBrush(fc)
                base = my(max(y0, 0.0))
                p.drawPolygon(QPolygonF([QPointF(pts[0].x(), base)] + pts + [QPointF(pts[-1].x(), base)]))
            p.setBrush(Qt.NoBrush)
            pen = QPen(col, s.get("width", 1.6))
            if s.get("dash"):
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawPolyline(QPolygonF(pts))
        for v, col in self.vlines:
            p.setPen(QPen(QColor(col), 1.4))
            p.drawLine(QPointF(mx(v), Tm), QPointF(mx(v), Tm + ph))
        p.setClipping(False)
        p.setPen(QPen(QColor(C["border"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(L, Tm, pw, ph))
