"""Regions of interest. Coordinates are image pixels; pixel (i, j) spans [j, j+1) x [i, i+1)."""
from __future__ import annotations

import math

import numpy as np
from skimage import draw


class Roi:
    AREA = ("rect", "ellipse", "polygon", "freehand")

    def __init__(self, kind, pts, name="", cats=None):
        self.kind = kind
        self.pts = [(float(x), float(y)) for x, y in pts]
        self.name = name
        self.cats = list(cats) if cats is not None else ([0] * len(self.pts) if kind == "point" else [])

    @property
    def is_area(self):
        return self.kind in self.AREA

    def copy(self):
        return Roi(self.kind, self.pts, self.name, self.cats)

    def bounds(self):
        xs = [p[0] for p in self.pts]
        ys = [p[1] for p in self.pts]
        return min(xs), min(ys), max(xs), max(ys)

    def move(self, dx, dy):
        return Roi(self.kind, [(x + dx, y + dy) for x, y in self.pts], self.name, self.cats)

    def mask(self, shape):
        H, W = shape
        m = np.zeros((H, W), bool)
        if not self.pts:
            return m
        x0, y0, x1, y1 = self.bounds()
        if self.kind == "rect":
            xa, ya, xb, yb = (int(round(v)) for v in (x0, y0, x1, y1))
            m[max(ya, 0):max(min(yb, H), 0), max(xa, 0):max(min(xb, W), 0)] = True
        elif self.kind == "ellipse":
            rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
            if rx > 0 and ry > 0:
                ya, yb = max(int(math.floor(y0)), 0), min(int(math.ceil(y1)), H)
                xa, xb = max(int(math.floor(x0)), 0), min(int(math.ceil(x1)), W)
                if yb > ya and xb > xa:
                    yy, xx = np.mgrid[ya:yb, xa:xb]
                    m[ya:yb, xa:xb] = (((xx + .5 - (x0 + rx)) / rx) ** 2 +
                                       ((yy + .5 - (y0 + ry)) / ry) ** 2) <= 1
        elif self.kind in ("polygon", "freehand"):
            if len(self.pts) >= 3:
                rr, cc = draw.polygon(np.array([p[1] for p in self.pts]) - .5,
                                      np.array([p[0] for p in self.pts]) - .5, (H, W))
                m[rr, cc] = True
        elif self.kind == "line":
            (ax, ay), (bx, by) = self.pts[0], self.pts[-1]
            rr, cc = draw.line(int(ay), int(ax), int(by), int(bx))
            ok = (rr >= 0) & (rr < H) & (cc >= 0) & (cc < W)
            m[rr[ok], cc[ok]] = True
        elif self.kind == "point":
            for x, y in self.pts:
                if 0 <= int(y) < H and 0 <= int(x) < W:
                    m[int(y), int(x)] = True
        return m

    def contains(self, x, y):
        if not self.pts:
            return False
        x0, y0, x1, y1 = self.bounds()
        if self.kind == "rect":
            return x0 <= x <= x1 and y0 <= y <= y1
        if self.kind == "ellipse":
            rx, ry = (x1 - x0) / 2, (y1 - y0) / 2
            return rx > 0 and ry > 0 and ((x - x0 - rx) / rx) ** 2 + ((y - y0 - ry) / ry) ** 2 <= 1
        if self.kind in ("polygon", "freehand"):
            inside = False
            n = len(self.pts)
            for i in range(n):
                (xa, ya), (xb, yb) = self.pts[i], self.pts[(i + 1) % n]
                if (ya > y) != (yb > y) and x < (xb - xa) * (y - ya) / (yb - ya) + xa:
                    inside = not inside
            return inside
        return False

    def distance_to_line(self, x, y):
        (ax, ay), (bx, by) = self.pts[0], self.pts[-1]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / L2))
        return math.hypot(x - ax - t * dx, y - ay - t * dy)

    def length(self):
        """Line length, or outline length for area shapes (pixels)."""
        x0, y0, x1, y1 = self.bounds()
        if self.kind == "line":
            return math.hypot(self.pts[-1][0] - self.pts[0][0], self.pts[-1][1] - self.pts[0][1])
        if self.kind == "rect":
            return 2 * ((x1 - x0) + (y1 - y0))
        if self.kind == "ellipse":
            a, b = (x1 - x0) / 2, (y1 - y0) / 2
            return math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))
        if self.kind in ("polygon", "freehand"):
            n = len(self.pts)
            return sum(math.hypot(self.pts[(i + 1) % n][0] - self.pts[i][0],
                                  self.pts[(i + 1) % n][1] - self.pts[i][1]) for i in range(n))
        return 0.0

    def angle(self):
        (ax, ay), (bx, by) = self.pts[0], self.pts[-1]
        return math.degrees(math.atan2(-(by - ay), bx - ax))

    def to_dict(self):
        return {"kind": self.kind, "pts": self.pts, "name": self.name, "cats": self.cats}

    @staticmethod
    def from_dict(d):
        return Roi(d["kind"], d["pts"], d.get("name", ""), d.get("cats"))

    def signature(self):
        return (self.kind, tuple((round(x, 2), round(y, 2)) for x, y in self.pts))
