"""Measurements on regions and particle analysis. Column names follow the ImageJ convention."""
from __future__ import annotations

import math

import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import ConvexHull
from scipy.spatial.distance import pdist
from skimage import measure as skm, segmentation

_S8 = np.ones((3, 3), bool)


def hull_metrics(mask):
    """(max Feret, min Feret, convex area) of a mask in pixels, measured on pixel corners."""
    edge = mask & ~ndi.binary_erosion(mask, border_value=0)
    ys, xs = np.nonzero(edge)
    if xs.size == 0:
        return 0.0, 0.0, 0.0
    pts = np.concatenate([np.c_[xs, ys], np.c_[xs + 1, ys], np.c_[xs, ys + 1], np.c_[xs + 1, ys + 1]]).astype(float)
    try:
        hull = pts[ConvexHull(pts).vertices]      # counter-clockwise
    except Exception:
        return (float(pdist(pts).max()) if len(pts) > 1 else 1.0), 1.0, float(mask.sum())
    fmax = float(pdist(hull).max())
    nxt = np.roll(hull, -1, axis=0)
    e = nxt - hull
    n = np.c_[-e[:, 1], e[:, 0]] / np.maximum(np.hypot(e[:, 0], e[:, 1]), 1e-12)[:, None]
    widths = np.abs(np.einsum("ijk,ik->ij", hull[None, :, :] - hull[:, None, :], n))
    area = 0.5 * abs(float(np.sum(hull[:, 0] * nxt[:, 1] - nxt[:, 0] * hull[:, 1])))
    return fmax, float(widths.max(axis=1).min()), area


def feret(mask):
    return hull_metrics(mask)[:2]


def _shape(region, px, perimeter=None):
    area = float(region.area)
    perim = float(region.perimeter if perimeter is None else perimeter)
    major = float(getattr(region, "axis_major_length", None) or 0.0)
    minor = float(getattr(region, "axis_minor_length", None) or 0.0)
    fmax, fmin, convex = hull_metrics(region.image)
    circ = min(1.0, 4 * math.pi * area / perim ** 2) if perim > 0 else 1.0
    return {
        "Perim.": perim * px,
        "Circ.": circ,
        "AR": major / minor if minor > 0 else 1.0,
        "Round": min(1.0, minor / major) if major > 0 else 1.0,
        "Solidity": min(1.0, area / convex) if convex > 0 else 1.0,
        "Feret": fmax * px,
        "MinFeret": fmin * px,
    }


def _intensity(vals, area_px, px):
    vals = np.asarray(vals, np.float64)
    if vals.size == 0:
        return {"Area": 0.0, "Mean": 0.0, "StdDev": 0.0, "Min": 0.0, "Max": 0.0,
                "Median": 0.0, "IntDen": 0.0, "RawIntDen": 0.0}
    mean = float(vals.mean())
    return {"Area": area_px * px * px, "Mean": mean,
            "StdDev": float(vals.std(ddof=1)) if vals.size > 1 else 0.0,
            "Min": float(vals.min()), "Max": float(vals.max()), "Median": float(np.median(vals)),
            "IntDen": area_px * px * px * mean, "RawIntDen": float(vals.sum())}


def measure_roi(doc, roi=None, frame=None):
    """Measure the active gray plane inside ``roi`` (whole image when None). Returns a list of rows."""
    f = doc.frame if frame is None else frame
    g = doc.gray(f)
    px = doc.pixel_size
    label = doc.name + (":" + roi.name if roi is not None and roi.name else "")
    tail = {"Ch": doc.channel + 1, "Frame": f + 1}
    if roi is not None and roi.kind == "point":
        rows = []
        for (x, y), cat in zip(roi.pts, roi.cats):
            inside = 0 <= int(y) < doc.H and 0 <= int(x) < doc.W
            rows.append({"Label": label, "X": x * px, "Y": y * px, "Type": cat + 1,
                         "Value": float(g[int(y), int(x)]) if inside else float("nan"), **tail})
        return rows
    if roi is not None and roi.kind == "line":
        prof = line_profile(g, roi)
        return [{"Label": label, "Length": roi.length() * px, "Angle": roi.angle(),
                 "Mean": float(prof.mean()) if prof.size else 0.0,
                 "Min": float(prof.min()) if prof.size else 0.0,
                 "Max": float(prof.max()) if prof.size else 0.0, **tail}]
    mask = np.ones(g.shape, bool) if roi is None else roi.mask(g.shape)
    n = int(mask.sum())
    row = {"Label": label, **_intensity(g[mask], n, px)}
    if n:
        ys, xs = np.nonzero(mask)
        row["X"], row["Y"] = float(xs.mean() + .5) * px, float(ys.mean() + .5) * px
        region = skm.regionprops(mask.astype(np.uint8))[0]
        row.update(_shape(region, px, None if roi is None or roi.kind == "freehand" else roi.length()))
        tm = doc.threshold_mask(f)
        inside = (tm if tm is not None else (g != 0))[mask]
        row["%Area"] = 100.0 * float(inside.mean())
    row.update(tail)
    return [row]


def line_profile(plane, roi):
    (ax, ay), (bx, by) = roi.pts[0], roi.pts[-1]
    n = max(2, int(round(math.hypot(bx - ax, by - ay))) + 1)
    ys = np.linspace(ay - .5, by - .5, n)
    xs = np.linspace(ax - .5, bx - .5, n)
    return ndi.map_coordinates(plane.astype(np.float32), [ys, xs], order=1, mode="nearest")


def roi_profile(doc, roi):
    """Intensity profile for a line (along it) or rectangle (column means). Returns (x, y)."""
    g = doc.gray()
    if roi.kind == "line":
        y = line_profile(g, roi)
        return np.linspace(0, roi.length(), y.size) * doc.pixel_size, y
    x0, y0, x1, y1 = (int(round(v)) for v in roi.bounds())
    sub = g[max(y0, 0):y1, max(x0, 0):x1]
    if sub.size == 0:
        return np.zeros(0), np.zeros(0)
    y = sub.mean(axis=0)
    return np.arange(y.size) * doc.pixel_size, y


def histogram(values, bins=256, vrange=None):
    values = np.asarray(values)
    if values.dtype == np.uint8 and vrange is None:
        return np.bincount(values.ravel(), minlength=256).astype(np.float64), np.arange(257, dtype=float)
    lo, hi = vrange or (float(values.min()), float(values.max()))
    if hi <= lo:
        hi = lo + 1
    return np.histogram(values, bins=bins, range=(lo, hi))[0].astype(np.float64), np.linspace(lo, hi, bins + 1)


def analyze_labels(labels, intensity=None, px=1.0, min_size=0.0, max_size=0.0,
                   min_circ=0.0, max_circ=1.0, exclude_edges=False):
    """Filter a label image and measure every remaining object.

    Sizes are in calibrated units squared; ``max_size`` <= 0 means no upper limit.
    Returns (relabelled label image, rows, summary)."""
    H, W = labels.shape
    out = np.zeros(labels.shape, np.int32)
    rows = []
    for r in skm.regionprops(labels):
        area = r.area * px * px
        if area < min_size or (max_size > 0 and area > max_size):
            continue
        y0, x0, y1, x1 = r.bbox
        if exclude_edges and (y0 == 0 or x0 == 0 or y1 == H or x1 == W):
            continue
        sh = _shape(r, px)
        if not (min_circ <= sh["Circ."] <= max_circ):
            continue
        idx = len(rows) + 1
        out[y0:y1, x0:x1][r.image] = idx
        vals = intensity[y0:y1, x0:x1][r.image] if intensity is not None else np.ones(int(r.area))
        row = {"#": idx, **_intensity(vals, int(r.area), px),
               "X": float(r.centroid[1] + .5) * px, "Y": float(r.centroid[0] + .5) * px, **sh}
        rows.append(row)
    total = sum(r["Area"] for r in rows)
    summary = {"Count": len(rows), "Total Area": total,
               "Average Size": total / len(rows) if rows else 0.0,
               "%Area": 100.0 * float((out > 0).mean()),
               "Mean": float(np.mean([r["Mean"] for r in rows])) if rows else 0.0}
    return out, rows, summary


def analyze_particles(binary, intensity=None, include_holes=False, **kw):
    b = np.asarray(binary, bool)
    if include_holes:
        b = ndi.binary_fill_holes(b)
    labels, _ = ndi.label(b, structure=_S8)
    return analyze_labels(labels, intensity, **kw)


def outline_overlay(labels, color=(255, 214, 0, 255)):
    ov = np.zeros(labels.shape + (4,), np.uint8)
    ov[segmentation.find_boundaries(labels, mode="inner")] = color
    return ov


def mask_overlay(mask, color=(46, 204, 133, 96)):
    ov = np.zeros(mask.shape + (4,), np.uint8)
    ov[mask] = color
    return ov


def label_polygons(labels, max_points=160):
    """One polygon (list of (x, y)) per label, in label order."""
    polys = []
    for r in skm.regionprops(labels):
        y0, x0 = r.bbox[:2]
        cs = skm.find_contours(np.pad(r.image, 1).astype(float), 0.5)
        if not cs:
            continue
        c = max(cs, key=len)
        step = max(1, len(c) // max_points)
        polys.append([(float(p[1]) - .5 + x0, float(p[0]) - .5 + y0) for p in c[::step]])
    return polys
