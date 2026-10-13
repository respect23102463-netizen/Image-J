"""Analysis modules: gel / Western blot, cell counting, colocalization, fluorescence, wound healing."""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi, stats
from scipy.signal import find_peaks

from . import filters as flt
from .measure import analyze_labels

_S8 = np.ones((3, 3), bool)


# ---- gel / Western blot -----------------------------------------------------
def analyze_strip(plane, rect, axis="row", lanes=0, mode="auto", polarity="auto",
                  bg_radius=0, prominence=5.0, vmax=None):
    """Quantify the bands inside a rectangular strip.

    axis="row": bands lie side by side (one protein across lanes); the profile runs along x.
    axis="lane": bands are stacked (one lane); the profile runs along y.
    Band area = background-subtracted integrated density (intensity x pixels)."""
    H, W = plane.shape
    x0, y0, x1, y1 = (int(round(v)) for v in rect)
    x0, x1 = max(0, min(x0, x1)), min(W, max(x0, x1))
    y0, y1 = max(0, min(y0, y1)), min(H, max(y0, y1))
    sub = plane[y0:y1, x0:x1].astype(np.float64)
    if sub.shape[0] < 2 or sub.shape[1] < 2:
        raise ValueError("strip too small")
    prof = sub.mean(axis=0) if axis == "row" else sub.mean(axis=1)
    thick = sub.shape[0] if axis == "row" else sub.shape[1]
    n = prof.size
    if polarity == "auto":
        g = plane[::max(1, H // 400), ::max(1, W // 400)]
        dark_bands = float(np.median(g)) > (float(g.min()) + float(g.max())) / 2
    else:
        dark_bands = polarity == "dark"
    if dark_bands:
        prof = (vmax if vmax else float(plane.max())) - prof
    r = int(bg_radius) or (int(0.75 * n / lanes) if lanes else max(8, n // 6))
    r = max(3, min(r, n))
    sm = ndi.gaussian_filter1d(prof, 1.0, mode="nearest")
    base = ndi.grey_opening(sm, size=2 * r + 1, mode="nearest")
    base = np.minimum(ndi.uniform_filter1d(base, size=max(3, r), mode="nearest"), sm)
    sig = np.clip(prof - base, 0, None)
    bands = []
    if mode == "even" and lanes > 0:
        edges = np.linspace(0, n, lanes + 1).round().astype(int)
        for i in range(lanes):
            s, e = int(edges[i]), int(edges[i + 1])
            seg = sig[s:e]
            if seg.size:
                bands.append({"start": s, "end": e - 1, "peak": s + int(seg.argmax()),
                              "area": float(seg.sum()) * thick})
    else:
        ss = ndi.gaussian_filter1d(sig, 1.5, mode="nearest")
        if ss.max() > 0:
            peaks, props = find_peaks(ss, prominence=max(prominence, 0.1) / 100 * ss.max(),
                                      distance=max(2, n // ((lanes or 25) * 2)))
            if lanes and len(peaks) > lanes:
                peaks = np.sort(peaks[np.argsort(props["prominences"])[-lanes:]])
            for i, pk in enumerate(peaks):
                left = 0 if i == 0 else int(peaks[i - 1] + np.argmin(ss[peaks[i - 1]:pk + 1]))
                right = n - 1 if i == len(peaks) - 1 else int(pk + np.argmin(ss[pk:peaks[i + 1] + 1]))
                floor = 0.02 * ss[pk]
                s = int(pk)
                while s > left and ss[s - 1] > floor:
                    s -= 1
                e = int(pk)
                while e < right and ss[e + 1] > floor:
                    e += 1
                bands.append({"start": s, "end": e, "peak": int(pk),
                              "area": float(sig[s:e + 1].sum()) * thick})
    total = sum(b["area"] for b in bands)
    for i, b in enumerate(bands):
        b["index"] = i + 1
        b["percent"] = 100.0 * b["area"] / total if total > 0 else 0.0
    return {"profile": prof, "baseline": base, "signal": sig, "bands": bands,
            "dark_bands": dark_bands, "offset": x0 if axis == "row" else y0, "thickness": thick}


# ---- cells --------------------------------------------------------------------
def segment_cells(plane, sigma=1.5, bg_radius=0.0, method="otsu", background="auto",
                  split=True, tolerance=1.0):
    """Blur -> (background subtraction) -> auto threshold -> fill holes -> watershed split."""
    a = plane.astype(np.float32)
    if sigma > 0:
        a = ndi.gaussian_filter(a, sigma)
    t0 = flt.auto_threshold(a, method)
    dark = flt.is_dark_background(a, t0) if background == "auto" else background == "dark"
    if bg_radius > 0:
        a = flt.subtract_background(a, bg_radius, light_background=not dark)
        t0 = flt.auto_threshold(a, method)
    binary = ndi.binary_fill_holes((a > t0) if dark else (a < t0))
    if split:
        return flt.split_labels(binary, tolerance)
    return ndi.label(binary, structure=_S8)[0].astype(np.int32)


def count_cells(plane, px=1.0, min_size=0.0, max_size=0.0, min_circ=0.0, exclude_edges=False, **seg):
    labels = segment_cells(plane, **seg)
    return analyze_labels(labels, plane, px=px, min_size=min_size, max_size=max_size,
                          min_circ=min_circ, max_circ=1.0, exclude_edges=exclude_edges)


# ---- colocalization -------------------------------------------------------------
def _pearson(a, b):
    if a.size < 3:
        return 0.0
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def costes_thresholds(a, b):
    """Costes automatic thresholds: lower the threshold along the regression line until the
    pixels below it are no longer positively correlated."""
    va, vb = a.var(), b.var()
    cov = ((a - a.mean()) * (b - b.mean())).mean()
    if cov <= 0 or va == 0:
        return float(a.max()), float(b.max())
    m = (vb - va + np.sqrt((vb - va) ** 2 + 4 * cov * cov)) / (2 * cov)
    c = b.mean() - m * a.mean()
    lo, hi = float(a.min()), float(a.max())
    for _ in range(24):
        mid = (lo + hi) / 2
        below = (a < mid) | (b < m * mid + c)
        r = _pearson(a[below], b[below]) if below.sum() > 10 else 0.0
        if r > 0:
            hi = mid
        else:
            lo = mid
    return lo, float(m * lo + c)


def colocalization(p1, p2, mask=None, threshold="costes", t1=0.0, t2=0.0):
    a = p1.astype(np.float64)[mask] if mask is not None else p1.astype(np.float64).ravel()
    b = p2.astype(np.float64)[mask] if mask is not None else p2.astype(np.float64).ravel()
    if a.size < 3:
        raise ValueError("too few pixels")
    step = max(1, a.size // 300_000)
    sa, sb = a[::step], b[::step]
    if threshold == "costes":
        t1, t2 = costes_thresholds(sa, sb)
    elif threshold == "otsu":
        t1, t2 = flt.auto_threshold(sa), flt.auto_threshold(sb)
    elif threshold == "none":
        t1 = t2 = 0.0
    a_on, b_on = a > t1, b > t2
    both, either = a_on & b_on, a_on | b_on
    sum_a, sum_b = a[a_on].sum(), b[b_on].sum()
    prod = (a - a.mean()) * (b - b.mean())
    denom = np.sqrt((a * a).sum() * (b * b).sum())
    amax, bmax = max(float(a.max()), 1e-9), max(float(b.max()), 1e-9)
    hist = np.histogram2d(b, a, bins=128, range=[[0, bmax], [0, amax]])[0]
    return {
        "Pearson r": _pearson(a, b),
        "Pearson r (above thr.)": _pearson(a[both], b[both]),
        "Spearman": float(stats.spearmanr(sa, sb)[0]) if sa.std() > 0 and sb.std() > 0 else 0.0,
        "Overlap (MOC)": float((a * b).sum() / denom) if denom > 0 else 0.0,
        # thresholded Manders coefficients: fraction of above-threshold signal that co-occurs
        "M1": float(a[both].sum() / sum_a) if sum_a > 0 else 0.0,
        "M2": float(b[both].sum() / sum_b) if sum_b > 0 else 0.0,
        "ICQ": float((prod > 0).mean() - 0.5),
        "Thr1": float(t1), "Thr2": float(t2),
        "%Overlap area": 100.0 * float(both.sum() / either.sum()) if either.any() else 0.0,
        "N": int(a.size),
        "_hist": hist, "_xmax": amax, "_ymax": bmax,
    }


# ---- fluorescence ---------------------------------------------------------------
def auto_background(plane):
    """Mean of the pixels below the Otsu threshold."""
    t = flt.auto_threshold(plane)
    bg = plane[plane <= t]
    return float(bg.mean()) if bg.size else 0.0


def ctcf(plane, mask, background, px=1.0):
    """Corrected total cell fluorescence = IntDen - area x mean background."""
    vals = plane[mask].astype(np.float64)
    n = int(vals.size)
    area = n * px * px
    mean = float(vals.mean()) if n else 0.0
    return {"Area": area, "Mean": mean, "IntDen": area * mean, "Bkgd": background,
            "Mean-Bkgd": mean - background, "CTCF": area * (mean - background)}


# ---- wound healing --------------------------------------------------------------
def _drop_small(mask, min_px):
    lab, n = ndi.label(mask, structure=_S8)
    if n == 0:
        return mask
    sizes = np.bincount(lab.ravel())
    keep = sizes >= min_px
    keep[0] = False
    return keep[lab]


def detect_wound(plane, radius=8, sensitivity=1.0, min_area=1.0, keep_largest=False):
    """Find the cell-free gap from local texture (cells are textured, the gap is smooth).

    ``min_area`` is a percentage of the image: smaller gaps and smaller cell islands are ignored.
    Returns (mask, stats in pixels)."""
    a = plane.astype(np.float32)
    lo, hi = np.percentile(a, [0.5, 99.5])
    a = np.clip((a - lo) / (hi - lo), 0, 1) if hi > lo else np.zeros_like(a)
    size = 2 * int(radius) + 1
    m = ndi.uniform_filter(a, size)
    # local variance is linear in the fraction of the window covered by cells, so thresholding it
    # half-way puts the boundary on the true edge (standard deviation would bias it into the gap)
    var = np.maximum(ndi.uniform_filter(a * a, size) - m * m, 0)
    var = ndi.gaussian_filter(var, max(1.0, radius / 2))
    t = flt.auto_threshold(var, "otsu") * float(sensitivity)
    wound = var < t
    min_px = max(1, int(a.size * min_area / 100.0))
    wound = _drop_small(wound, min_px)
    wound = ~_drop_small(~wound, min_px)
    if keep_largest and wound.any():
        lab, n = ndi.label(wound, structure=_S8)
        if n > 1:
            wound = lab == (1 + int(np.argmax(ndi.sum(wound, lab, range(1, n + 1)))))
    area = int(wound.sum())
    rows, cols = int(wound.any(axis=1).sum()), int(wound.any(axis=0).sum())
    length = max(rows, cols)
    return wound, {"area": area, "percent": 100.0 * area / a.size,
                   "width": area / length if length else 0.0}
