"""Pixel operations. Plane functions take and return 2-D float32 arrays;
binary functions take and return boolean masks."""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi
from skimage import exposure, filters as skf, morphology as morph, restoration, segmentation, transform

THRESHOLD_METHODS = ["otsu", "li", "triangle", "yen", "isodata", "mean", "minimum"]
_S8 = np.ones((3, 3), bool)


def _disk(radius):
    return morph.disk(max(1, int(round(radius))))


# ---- filters --------------------------------------------------------------
def gaussian(a, sigma=2.0):
    return ndi.gaussian_filter(a, sigma)


def median(a, radius=2):
    return ndi.median_filter(a, footprint=_disk(radius))


def mean(a, radius=2):
    return ndi.uniform_filter(a, 2 * int(radius) + 1)


def minimum(a, radius=1):
    return ndi.minimum_filter(a, footprint=_disk(radius))


def maximum(a, radius=1):
    return ndi.maximum_filter(a, footprint=_disk(radius))


def variance(a, radius=2):
    size = 2 * int(radius) + 1
    m = ndi.uniform_filter(a, size)
    return np.maximum(ndi.uniform_filter(a * a, size) - m * m, 0)


def unsharp(a, sigma=1.0, amount=0.6):
    amount = min(max(amount, 0.0), 0.95)
    return (a - amount * ndi.gaussian_filter(a, sigma)) / (1 - amount)


def smooth(a):
    return ndi.uniform_filter(a, 3)


def sharpen(a):
    k = np.array([[-1, -1, -1], [-1, 12, -1], [-1, -1, -1]], np.float32) / 4
    return ndi.convolve(a, k, mode="nearest")


def find_edges(a):
    return np.hypot(ndi.sobel(a, 1), ndi.sobel(a, 0))


def bandpass(a, large=40.0, small=3.0):
    lo = ndi.gaussian_filter(a, small / 2.0) if small > 0 else a
    return lo - ndi.gaussian_filter(a, large / 2.0) + a.mean()


def subtract_background(a, radius=50.0, light_background=False):
    """Rolling-ball background subtraction (computed on a shrunken image for speed)."""
    top = float(a.max())
    work = (top - a) if light_background else a
    shrink = 1 if radius <= 10 else 2 if radius <= 30 else 4 if radius <= 100 else 8
    H, W = work.shape
    ph, pw = (-H) % shrink, (-W) % shrink
    small = np.pad(work, ((0, ph), (0, pw)), mode="edge")
    small = small.reshape(small.shape[0] // shrink, shrink, small.shape[1] // shrink, shrink).min((1, 3))
    small = ndi.uniform_filter(small, 3)
    bg = restoration.rolling_ball(small, radius=max(1.0, radius / shrink))
    if shrink > 1:
        bg = transform.resize(bg, (H + ph, W + pw), order=1, mode="edge", anti_aliasing=False)[:H, :W]
    out = work - np.minimum(bg, work)
    return (top - out) if light_background else out


# ---- math -----------------------------------------------------------------
def invert(a, _max=None):
    if _max == 255.0:
        return 255.0 - a
    return float(a.min()) + float(a.max()) - a


def add(a, value=25.0):
    return a + value


def subtract(a, value=25.0):
    return a - value


def multiply(a, value=1.25):
    return a * value


def divide(a, value=1.25):
    return a / value if value else a


def gamma(a, value=0.5, _max=None):
    m = _max or float(a.max()) or 1.0
    return m * (np.clip(a, 0, None) / m) ** value


def log(a, _max=None):
    m = _max or float(a.max()) or 1.0
    return np.where(a > 1, np.log(np.maximum(a, 1)) * (m / np.log(max(m, 2.0))), 0)


def sqrt(a):
    return np.sqrt(np.clip(a, 0, None))


def enhance_contrast(a, saturated=0.35, _max=None):
    lo, hi = np.percentile(a, [saturated / 2, 100 - saturated / 2])
    if hi <= lo:
        return a
    return np.clip((a - lo) / (hi - lo), 0, 1) * (_max or float(a.max()) or 1.0)


def equalize(a, _max=None):
    return exposure.equalize_hist(a) * (_max or float(a.max()) or 1.0)


def clahe(a, clip_limit=0.01, _max=None):
    lo, hi = float(a.min()), float(a.max())
    if hi <= lo:
        return a
    return exposure.equalize_adapthist((a - lo) / (hi - lo), clip_limit=clip_limit) * (_max or hi)


def distance_map(a):
    return ndi.distance_transform_edt(a > 0)


# ---- binary ---------------------------------------------------------------
def erode(b, iterations=1):
    return ndi.binary_erosion(b, _S8, iterations=int(iterations), border_value=1)


def dilate(b, iterations=1):
    return ndi.binary_dilation(b, _S8, iterations=int(iterations))


def open_(b, iterations=1):
    return dilate(erode(b, iterations), iterations)


def close_(b, iterations=1):
    return erode(dilate(b, iterations), iterations)


def fill_holes(b):
    return ndi.binary_fill_holes(b)


def outline(b):
    return b & ~ndi.binary_erosion(b, _S8, border_value=1)


def skeletonize(b):
    return morph.skeletonize(b)


def split_labels(b, tolerance=1.0):
    """Label objects, separating touching ones with a distance-transform watershed.

    One seed is placed on every maximum of the distance map that rises more than ``tolerance``
    above its surroundings (an h-maxima transform, evaluated per object so that large images
    stay fast)."""
    b = np.asarray(b, bool)
    if not b.any():
        return np.zeros(b.shape, np.int32)
    dist = ndi.gaussian_filter(ndi.distance_transform_edt(b).astype(np.float32), 1.0)
    comp, n = ndi.label(b, structure=_S8)
    h = max(float(tolerance), 1e-3)
    markers = np.zeros(b.shape, np.int32)
    count = 0
    for i, sl in enumerate(ndi.find_objects(comp), 1):
        inside = comp[sl] == i
        d = np.where(inside, dist[sl], 0)
        if d.max() <= h or inside.sum() < 9:
            seeds = d == d.max()
        else:
            seeds = (morph.h_maxima(np.pad(d, 1), h)[1:-1, 1:-1] > 0) & inside
        lab, k = ndi.label(seeds, structure=_S8)
        markers[sl][lab > 0] = lab[lab > 0] + count
        count += k
    return segmentation.watershed(-dist, markers, mask=b).astype(np.int32)


def watershed(b, tolerance=1.0):
    labels = split_labels(b, tolerance)
    return (labels > 0) & ~_touching(labels)


def _touching(labels):
    """Pixels that border a *different* non-zero label."""
    out = np.zeros(labels.shape, bool)
    for sh in ((0, 1), (1, 0), (1, 1), (1, -1)):
        a = labels
        b = np.roll(labels, sh, (0, 1))
        hit = (a != b) & (a > 0) & (b > 0)
        if sh[0]:
            hit[0, :] = False
        if sh[1] > 0:
            hit[:, 0] = False
        if sh[1] < 0:
            hit[:, -1] = False
        out |= hit
    return out


# ---- threshold ------------------------------------------------------------
def auto_threshold(a, method="otsu"):
    a = np.asarray(a)
    v = a.ravel()
    if v.size > 1_000_000:
        v = v[::v.size // 1_000_000]
    v = v[np.isfinite(v)]
    if v.size == 0 or v.min() == v.max():
        return float(v.min()) if v.size else 0.0
    try:
        return float(getattr(skf, "threshold_" + method)(v))
    except Exception:
        return float(skf.threshold_otsu(v))


def is_dark_background(a, t):
    """Objects are assumed to cover less than half of the image."""
    return float((np.asarray(a) > t).mean()) < 0.5


def is_binary(a):
    top = a.max()
    return bool(((a == 0) | (a == top)).all())
