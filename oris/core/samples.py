"""Synthetic sample images with known ground truth, for teaching and for the test-suite."""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi

from .image import ImageDoc

BLOT_TARGET = [1.0, 0.8, 0.6, 0.45, 0.3, 0.15]
NUCLEI_COUNT = 60
WOUND_WIDTHS = [220, 140, 60]


def blot(seed=1):
    """Western blot: target row with known relative amounts, loading-control row with equal bands."""
    rng = np.random.default_rng(seed)
    H, W = 300, 560
    img = np.full((H, W), 232.0)
    img += ndi.gaussian_filter(rng.normal(0, 30, (H, W)), 40)
    for row_y, amounts in ((95, BLOT_TARGET), (205, [1.0] * 6)):
        for i, amt in enumerate(amounts):
            band = np.zeros((H, W))
            cx = 70 + i * 84
            band[row_y - 9:row_y + 9, cx - 26:cx + 26] = 1.0
            img -= ndi.gaussian_filter(band, 3.5) * 150 * amt
    img += rng.normal(0, 2.0, (H, W))
    return ImageDoc(np.clip(img, 0, 255).astype(np.uint8), "sample-blot")


def nuclei(seed=2):
    """Fluorescent nuclei on a dark background; several pairs touch."""
    rng = np.random.default_rng(seed)
    H = W = 512
    yy, xx = np.mgrid[:H, :W]
    img = np.zeros((H, W))
    centers = []
    while len(centers) < NUCLEI_COUNT:
        x, y, r = rng.uniform(30, W - 30), rng.uniform(30, H - 30), rng.uniform(8, 12)
        if len(centers) % 6 == 5:       # make a touching neighbour
            px, py, pr = centers[-1]
            ang = rng.uniform(0, 2 * np.pi)
            x, y = px + np.cos(ang) * (pr + r) * 1.05, py + np.sin(ang) * (pr + r) * 1.05
            if not (25 < x < W - 25 and 25 < y < H - 25):
                continue
            others = centers[:-1]
        else:
            others = centers
        if any(np.hypot(x - cx, y - cy) < (r + cr) * 1.25 for cx, cy, cr in others):
            continue
        centers.append((x, y, r))
        img = np.maximum(img, np.clip(1.5 - np.hypot(xx - x, yy - y) / r * 1.2, 0, 1) * rng.uniform(0.7, 1.0))
    img = ndi.gaussian_filter(img, 1.2) * 190 + 18 + rng.normal(0, 4, (H, W))
    return ImageDoc(np.clip(img, 0, 255).astype(np.uint8), "sample-nuclei", pixel_size=0.5, unit="µm")


def fluorescence(seed=3):
    """Two-channel 16-bit image; about half of the channel-2 spots sit on channel-1 spots."""
    rng = np.random.default_rng(seed)
    H = W = 512
    yy, xx = np.mgrid[:H, :W]

    def spots(points):
        im = np.zeros((H, W))
        for x, y, r, k in points:
            im += np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * r * r)) * k
        return im

    def rand(n):
        return [(rng.uniform(20, W - 20), rng.uniform(20, H - 20), rng.uniform(5, 9), rng.uniform(.6, 1))
                for _ in range(n)]
    shared, only1, only2 = rand(35), rand(25), rand(25)
    c1 = spots(shared + only1) * 9000 + 400 + rng.normal(0, 60, (H, W))
    c2 = spots(shared + only2) * 7000 + 300 + rng.normal(0, 60, (H, W))
    doc = ImageDoc(np.clip(np.stack([c1, c2]), 0, 65535).astype(np.uint16)[None], "sample-fluorescence",
                   pixel_size=0.25, unit="µm")
    doc.luts = ["green", "magenta"]
    return doc


def wound(seed=4):
    """Scratch-assay time series (3 frames); the gap narrows from 220 to 60 px on a 640 px wide field."""
    rng = np.random.default_rng(seed)
    H, W = 420, 640
    frames = []
    for width in WOUND_WIDTHS:
        tex = ndi.gaussian_filter(rng.normal(0, 1, (H, W)), 1.5) - ndi.gaussian_filter(rng.normal(0, 1, (H, W)), 6)
        tex = tex / tex.std() * 34
        edge_l = W / 2 - width / 2 + ndi.gaussian_filter1d(rng.normal(0, 30, H), 12)
        edge_r = W / 2 + width / 2 + ndi.gaussian_filter1d(rng.normal(0, 30, H), 12)
        xs = np.arange(W)[None, :]
        cells = (xs < edge_l[:, None]) | (xs > edge_r[:, None])
        img = 128 + np.where(cells, tex, 0) + rng.normal(0, 2.5, (H, W))
        frames.append(np.clip(img, 0, 255).astype(np.uint8))
    return ImageDoc(np.stack(frames), "sample-wound", pixel_size=1.3, unit="µm")


SAMPLES = {"blot": blot, "nuclei": nuclei, "fluorescence": fluorescence, "wound": wound}
