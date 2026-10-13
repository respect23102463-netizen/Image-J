"""Image canvas: zoom/pan, selection tools, overlays."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView
from skimage import measure as skm, segmentation

from ..core.roi import Roi
from .theme import C, CATEGORY_COLORS

ROI_COLOR = "#ffd400"
SAVED_COLOR = "#35d0ba"
TOOLS = ["rect", "ellipse", "polygon", "freehand", "line", "point", "wand", "hand", "zoom"]


def rgb_qimage(a):
    a = np.ascontiguousarray(a)
    return QImage(a.data, a.shape[1], a.shape[0], 3 * a.shape[1], QImage.Format_RGB888).copy()


def rgba_qimage(a):
    a = np.ascontiguousarray(a)
    return QImage(a.data, a.shape[1], a.shape[0], 4 * a.shape[1], QImage.Format_RGBA8888).copy()


def overlay_array(doc, frame=None):
    """RGBA overlay for a frame: analysis overlay plus the red threshold mask."""
    f = doc.frame if frame is None else frame
    ov = doc.overlays.get(f)
    tm = doc.threshold_mask(f)
    if ov is None and tm is None:
        return None
    out = np.zeros((doc.H, doc.W, 4), np.uint8) if ov is None else ov.copy()
    if tm is not None:
        out[tm] = (255, 45, 45, 150)
    return out


def roi_handles(roi):
    if roi.kind in ("rect", "ellipse"):
        x0, y0, x1, y1 = roi.bounds()
        xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (xm, y0), (x1, ym), (xm, y1), (x0, ym)]
    if roi.kind == "line" or (roi.kind == "polygon" and len(roi.pts) <= 80):
        return list(roi.pts)
    return []


def _draw_roi(p, roi, mp, color, label=None, handles=False):
    pen = QPen(QColor(color), 1.5)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    if not roi.pts:
        return
    if roi.kind in ("rect", "ellipse"):
        x0, y0, x1, y1 = roi.bounds()
        r = QRectF(mp(x0, y0), mp(x1, y1))
        p.drawRect(r) if roi.kind == "rect" else p.drawEllipse(r)
        anchor = mp(x0, y0)
    elif roi.kind in ("polygon", "freehand"):
        p.drawPolygon(QPolygonF([mp(x, y) for x, y in roi.pts]))
        anchor = mp(*roi.pts[0])
    elif roi.kind == "line":
        p.drawLine(mp(*roi.pts[0]), mp(*roi.pts[-1]))
        anchor = mp(*roi.pts[0])
    else:
        font = QFont(p.font())
        font.setPixelSize(10)
        p.setFont(font)
        for i, ((x, y), cat) in enumerate(zip(roi.pts, roi.cats)):
            c = QColor(CATEGORY_COLORS[cat % len(CATEGORY_COLORS)])
            q = mp(x, y)
            p.setPen(QPen(QColor(0, 0, 0, 200), 3))
            p.drawEllipse(q, 3.5, 3.5)
            p.setPen(QPen(c, 1.5))
            p.setBrush(c)
            p.drawEllipse(q, 3, 3)
            p.setBrush(Qt.NoBrush)
            if len(roi.pts) <= 400:
                p.drawText(q + QPointF(5, -4), str(i + 1))
        return
    if label:
        font = QFont(p.font())
        font.setPixelSize(11)
        p.setFont(font)
        p.setPen(QColor(color))
        p.drawText(anchor + QPointF(3, -3), label)
    if handles:
        p.setPen(QPen(QColor(0, 0, 0), 1))
        p.setBrush(QColor("#ffffff"))
        for x, y in roi_handles(roi):
            q = mp(x, y)
            p.drawRect(QRectF(q.x() - 3, q.y() - 3, 6, 6))


def paint_annotations(p, doc, mp, zoom, frame=None, show_all=True, handles=False, pending=None, cursor=None):
    """Draw ROIs, object labels and the scale bar. ``mp`` maps image to device coordinates."""
    f = doc.frame if frame is None else frame
    p.setRenderHint(QPainter.Antialiasing, True)
    labels = doc.labels.get(f)
    if labels and (zoom >= 0.35 or len(labels) < 200):
        font = QFont(p.font())
        font.setPixelSize(int(max(9, min(15, 10 * zoom))))
        p.setFont(font)
        p.setPen(QColor("#ffe45c"))
        for x, y, text in labels:
            q = mp(x, y)
            p.drawText(QRectF(q.x() - 20, q.y() - 8, 40, 16), Qt.AlignCenter, text)
    if show_all:
        for i, roi in enumerate(doc.rois):
            _draw_roi(p, roi, mp, SAVED_COLOR, roi.name or str(i + 1))
    if doc.active_roi is not None:
        _draw_roi(p, doc.active_roi, mp, ROI_COLOR, handles=handles)
    if pending:
        p.setPen(QPen(QColor(ROI_COLOR), 1.5))
        pts = [mp(x, y) for x, y in pending] + ([mp(*cursor)] if cursor else [])
        p.drawPolyline(QPolygonF(pts))
        p.setBrush(QColor("#ffffff"))
        p.setPen(QPen(QColor(0, 0, 0), 1))
        q = pts[0]
        p.drawRect(QRectF(q.x() - 3.5, q.y() - 3.5, 7, 7))
    sb = doc.scale_bar
    if sb:
        length_px = sb["length"] / doc.pixel_size
        margin = 0.035 * min(doc.W, doc.H)
        th = sb["thickness"]
        x0 = margin if "left" in sb["position"] else doc.W - margin - length_px
        y0 = margin if "upper" in sb["position"] else doc.H - margin - th
        col = QColor({"white": "#ffffff", "black": "#000000", "yellow": "#ffd400"}.get(sb["color"], "#ffffff"))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        a, b = mp(x0, y0), mp(x0 + length_px, y0 + th)
        p.drawRect(QRectF(a, b))
        if sb.get("label"):
            font = QFont(p.font())
            font.setPixelSize(int(max(9, th * 3.2 * zoom)))
            font.setBold(True)
            p.setFont(font)
            p.setPen(col)
            text = f"{sb['length']:g} {doc.unit}"
            hgt = font.pixelSize() + 4
            rect = QRectF(a.x() - 200, a.y() - hgt - 2, (b.x() - a.x()) + 400, hgt)
            p.drawText(rect, Qt.AlignHCenter | Qt.AlignBottom, text)


def flatten(doc, frame=None):
    """The view with overlays, selections and scale bar burned in, as a QImage."""
    img = rgb_qimage(doc.render(frame)).convertToFormat(QImage.Format_RGB32)
    p = QPainter(img)
    ov = overlay_array(doc, frame)
    if ov is not None:
        p.drawImage(0, 0, rgba_qimage(ov))
    paint_annotations(p, doc, lambda x, y: QPointF(x, y), 1.0, frame)
    p.end()
    return img


class Canvas(QGraphicsView):
    mouseMoved = Signal(float, float)
    roiChanged = Signal()
    zoomChanged = Signal(float)

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.tool = "rect"
        self.category = 0
        self.show_all = True
        self.preview = None
        self._drag = None
        self._poly = None
        self._cursor = None
        self._pan = None
        self._space = False
        scene = QGraphicsScene(self)
        self.setScene(scene)
        self.pix = scene.addPixmap(QPixmap())
        self.ovl = scene.addPixmap(QPixmap())
        self.ovl.setZValue(1)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setAcceptDrops(False)      # let the main window receive dropped files
        self.setBackgroundBrush(QColor(C["canvas"]))
        self._fitted = False
        self._follow = True
        self.refresh()

    # ---- display ------------------------------------------------------
    def refresh(self):
        doc = self.doc
        self.setBackgroundBrush(QColor(C["canvas"]))
        img = self.preview if self.preview is not None else doc.render()
        self.pix.setPixmap(QPixmap.fromImage(rgb_qimage(img)))
        ov = overlay_array(doc) if self.preview is None else None
        if ov is None:
            self.ovl.setVisible(False)
        else:
            self.ovl.setPixmap(QPixmap.fromImage(rgba_qimage(ov)))
            self.ovl.setVisible(True)
        rect = QRectF(0, 0, doc.W, doc.H)
        if self.sceneRect() != rect:
            self.setSceneRect(rect)
            self._fitted = False
            if self.isVisible():
                self.fit()
        self._smooth()
        self.viewport().update()

    def set_preview(self, rgb):
        self.preview = rgb
        self.refresh()

    def zoom(self):
        return self.transform().m11()

    def _smooth(self):
        mode = Qt.SmoothTransformation if self.zoom() < 1 else Qt.FastTransformation
        self.pix.setTransformationMode(mode)
        self.ovl.setTransformationMode(Qt.FastTransformation)

    def set_zoom(self, z, anchor_center=True, user=True):
        if user:
            self._follow = False        # the user chose a zoom: stop re-fitting on window resize
        z = max(0.02, min(64.0, z))
        if anchor_center:
            self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        f = z / self.zoom()
        self.scale(f, f)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._smooth()
        self.zoomChanged.emit(self.zoom())

    def fit(self):
        vw, vh = self.viewport().width() - 8, self.viewport().height() - 8
        if vw > 10 and vh > 10:
            self.set_zoom(min(vw / self.doc.W, vh / self.doc.H, 8.0), user=False)
            self.centerOn(self.doc.W / 2, self.doc.H / 2)
            self._fitted = True
            self._follow = True

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._fitted or self._follow:
            self.fit()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._fitted or self._follow:
            self.fit()

    def viewportEvent(self, e):
        # trackpad pinch (macOS) zooms around the fingers
        if e.type() == QEvent.NativeGesture and e.gestureType() == Qt.ZoomNativeGesture:
            self.set_zoom(self.zoom() * (1.0 + e.value()), anchor_center=False)
            return True
        return super().viewportEvent(e)

    def drawForeground(self, painter, rect):
        painter.save()
        t = self.viewportTransform()
        painter.resetTransform()
        paint_annotations(painter, self.doc, lambda x, y: t.map(QPointF(x, y)), self.zoom(),
                          show_all=self.show_all, handles=True, pending=self._poly, cursor=self._cursor)
        painter.restore()

    # ---- helpers ------------------------------------------------------
    def _img(self, e):
        q = self.mapToScene(e.position().toPoint())
        return q.x(), q.y()

    def _near(self, a, b, tol=7.0):
        return math.hypot(a[0] - b[0], a[1] - b[1]) * self.zoom() <= tol

    def set_tool(self, tool):
        self.tool = tool
        self._poly = None
        cursors = {"hand": Qt.OpenHandCursor, "zoom": Qt.PointingHandCursor, "point": Qt.CrossCursor,
                   "wand": Qt.PointingHandCursor}
        self.viewport().setCursor(cursors.get(tool, Qt.CrossCursor))
        self.viewport().update()

    def set_roi(self, roi):
        self.doc.active_roi = roi
        self.viewport().update()
        self.roiChanged.emit()

    @staticmethod
    def _snap(kind, pts):
        if kind in ("rect", "ellipse"):
            return [(round(x), round(y)) for x, y in pts]
        return pts

    # ---- mouse --------------------------------------------------------
    def wheelEvent(self, e):
        # a mouse wheel (or Ctrl/Cmd + scroll) zooms; two-finger trackpad scrolling pans, as in other Mac apps
        pixel = e.pixelDelta()
        if not pixel.isNull() and not (e.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)):
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - pixel.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - pixel.y())
            self._follow = False
            return
        steps = e.angleDelta().y() / 120.0
        if steps:
            self.set_zoom(self.zoom() * (1.25 ** steps), anchor_center=False)

    def mousePressEvent(self, e):
        self.setFocus()
        p = self._img(e)
        roi = self.doc.active_roi
        if e.button() == Qt.MiddleButton or self._space or (self.tool == "hand" and e.button() == Qt.LeftButton):
            self._pan = e.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        if self.tool == "zoom":
            out = e.button() == Qt.RightButton or bool(e.modifiers() & Qt.AltModifier)
            self.set_zoom(self.zoom() * (0.5 if out else 2.0), anchor_center=False)
            return
        if e.button() == Qt.RightButton:
            if self.tool == "polygon" and self._poly:
                self._close_polygon()
            elif self.tool == "point" and roi is not None and roi.kind == "point":
                for i, q in enumerate(roi.pts):
                    if self._near(p, q, 9):
                        pts, cats = list(roi.pts), list(roi.cats)
                        del pts[i], cats[i]
                        self.set_roi(Roi("point", pts, roi.name, cats) if pts else None)
                        break
            return
        if e.button() != Qt.LeftButton:
            return
        if self.tool == "wand":
            self._wand(p)
            return
        if self.tool == "point":
            if roi is not None and roi.kind == "point":
                self.set_roi(Roi("point", roi.pts + [p], roi.name, roi.cats + [self.category]))
            else:
                self.set_roi(Roi("point", [p], cats=[self.category]))
            return
        if self.tool == "polygon":
            if self._poly is None:
                self._poly = [p]
                self.doc.active_roi = None
            elif len(self._poly) >= 3 and self._near(p, self._poly[0], 9):
                self._close_polygon()
            else:
                self._poly.append(p)
            self.viewport().update()
            return
        # rect / ellipse / line / freehand: edit the existing selection or start a new one
        if roi is not None and roi.kind != "point":
            for i, hpt in enumerate(roi_handles(roi)):
                if self._near(p, hpt):
                    self._drag = {"mode": "handle", "idx": i, "orig": roi.copy(), "start": p}
                    return
            hit = roi.contains(*p) if roi.is_area else (roi.kind == "line" and roi.distance_to_line(*p) * self.zoom() < 6)
            if hit:
                self._drag = {"mode": "move", "orig": roi.copy(), "start": p}
                return
        self._drag = {"mode": "create", "start": p, "pts": [p]}
        self.doc.active_roi = None
        self.viewport().update()

    def mouseMoveEvent(self, e):
        p = self._img(e)
        self._cursor = p
        self.mouseMoved.emit(*p)
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        d = self._drag
        if d is None:
            if self._poly:
                self.viewport().update()
            return
        sx, sy = d["start"]
        if d["mode"] == "create":
            if self.tool == "freehand":
                if not self._near(p, d["pts"][-1], 2):
                    d["pts"].append(p)
                if len(d["pts"]) >= 2:
                    self.doc.active_roi = Roi("freehand", d["pts"])
            else:
                x, y = p
                if e.modifiers() & Qt.ShiftModifier and self.tool in ("rect", "ellipse"):
                    side = max(abs(x - sx), abs(y - sy))
                    x, y = sx + math.copysign(side, x - sx), sy + math.copysign(side, y - sy)
                self.doc.active_roi = Roi(self.tool, self._snap(self.tool, [(sx, sy), (x, y)]))
        elif d["mode"] == "move":
            o = d["orig"]
            dx, dy = p[0] - sx, p[1] - sy
            if o.kind in ("rect", "ellipse"):
                dx, dy = round(dx), round(dy)
            self.doc.active_roi = o.move(dx, dy)
        else:
            o, i = d["orig"], d["idx"]
            if o.kind in ("rect", "ellipse"):
                x0, y0, x1, y1 = o.bounds()
                x, y = p
                if i in (0, 3, 7):
                    x0 = x
                if i in (1, 2, 5):
                    x1 = x
                if i in (0, 1, 4):
                    y0 = y
                if i in (2, 3, 6):
                    y1 = y
                self.doc.active_roi = Roi(o.kind, self._snap(o.kind, [(x0, y0), (x1, y1)]), o.name)
            else:
                pts = list(o.pts)
                pts[i] = p
                self.doc.active_roi = Roi(o.kind, pts, o.name)
        self.viewport().update()

    def mouseReleaseEvent(self, e):
        if self._pan is not None:
            self._pan = None
            self.set_tool(self.tool)
            return
        d, self._drag = self._drag, None
        if d is None:
            return
        roi = self.doc.active_roi
        if roi is not None:
            x0, y0, x1, y1 = roi.bounds()
            small = (x1 - x0 < 1 or y1 - y0 < 1) if roi.is_area else roi.length() < 1
            if small or (roi.kind == "freehand" and len(roi.pts) < 3):
                self.doc.active_roi = None
        self.viewport().update()
        self.roiChanged.emit()

    def mouseDoubleClickEvent(self, e):
        if self.tool == "polygon" and self._poly:
            self._close_polygon()
        else:
            super().mouseDoubleClickEvent(e)

    def leaveEvent(self, e):
        self._cursor = None
        super().leaveEvent(e)

    def _close_polygon(self):
        pts, self._poly = self._poly, None
        # a double click adds its first click as a duplicate vertex
        clean = [pts[0]]
        for q in pts[1:]:
            if not self._near(q, clean[-1], 2):
                clean.append(q)
        self.set_roi(Roi("polygon", clean) if len(clean) >= 3 else None)

    def _wand(self, p):
        doc = self.doc
        x, y = int(p[0]), int(p[1])
        if not (0 <= x < doc.W and 0 <= y < doc.H):
            return
        g = doc.gray().astype(np.float32)
        span = float(g.max() - g.min())
        mask = segmentation.flood(g, (y, x), tolerance=span * 0.08 if span > 0 else 0)
        cs = skm.find_contours(np.pad(mask, 1).astype(float), 0.5)
        if not cs:
            return
        c = max(cs, key=len)
        step = max(1, len(c) // 300)
        self.set_roi(Roi("polygon", [(float(q[1]) - .5, float(q[0]) - .5) for q in c[::step]]))

    # ---- keyboard -----------------------------------------------------
    def keyPressEvent(self, e):
        k = e.key()
        roi = self.doc.active_roi
        if k == Qt.Key_Space and not e.isAutoRepeat():
            self._space = True
            self.viewport().setCursor(Qt.OpenHandCursor)
        elif k == Qt.Key_Escape:
            if self._poly:
                self._poly = None
                self.viewport().update()
            else:
                self.set_roi(None)
        elif k in (Qt.Key_Return, Qt.Key_Enter) and self._poly:
            self._close_polygon()
        elif k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and roi is not None:
            dx = {Qt.Key_Left: -1, Qt.Key_Right: 1}.get(k, 0)
            dy = {Qt.Key_Up: -1, Qt.Key_Down: 1}.get(k, 0)
            self.set_roi(roi.move(dx, dy))
        elif k in (Qt.Key_Plus, Qt.Key_Equal):
            self.set_zoom(self.zoom() * 1.25)
        elif k == Qt.Key_Minus:
            self.set_zoom(self.zoom() / 1.25)
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = False
            self.set_tool(self.tool)
        else:
            super().keyReleaseEvent(e)
