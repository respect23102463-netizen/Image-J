"""Image document model. Pixel data is always stored as (F, C, Y, X)."""
from __future__ import annotations

import numpy as np

LUT_NAMES = ["grays", "inverted", "red", "green", "blue", "cyan", "magenta",
             "yellow", "fire", "viridis"]
DEFAULT_CHANNEL_LUTS = ["red", "green", "blue", "grays", "cyan", "magenta", "yellow"]


def _interp_lut(pos, cols):
    x = np.linspace(0, 1, 256)
    cols = np.asarray(cols, float)
    return np.stack([np.interp(x, pos, cols[:, i]) for i in range(3)], 1).round().astype(np.uint8)


def _make_lut(name):
    r = np.arange(256, dtype=np.uint8)
    z = np.zeros(256, np.uint8)
    simple = {"grays": (r, r, r), "inverted": (r[::-1],) * 3, "red": (r, z, z),
              "green": (z, r, z), "blue": (z, z, r), "cyan": (z, r, r),
              "magenta": (r, z, r), "yellow": (r, r, z)}
    if name in simple:
        return np.stack(simple[name], 1)
    if name == "fire":
        return _interp_lut([0, .12, .3, .45, .6, .8, 1.0],
                           [(0, 0, 0), (0, 0, 130), (125, 0, 180), (215, 25, 60),
                            (255, 120, 0), (255, 225, 0), (255, 255, 255)])
    return _interp_lut(np.linspace(0, 1, 9),
                       [(68, 1, 84), (71, 44, 122), (59, 81, 139), (44, 113, 142),
                        (33, 144, 141), (39, 173, 129), (92, 200, 99), (170, 220, 50),
                        (253, 231, 37)])


_LUTS = {n: _make_lut(n) for n in LUT_NAMES}


def get_lut(name):
    return _LUTS.get(name, _LUTS["grays"])


def normalize_dtype(a):
    """Coerce any array to one of the supported pixel types."""
    if a.dtype == np.bool_:
        return a.astype(np.uint8) * 255
    if a.dtype in (np.uint8, np.uint16, np.float32):
        return a
    return a.astype(np.float32)


def cast_like(r, dtype):
    """Convert a float result back to the pixel type, rounding and clipping."""
    r = np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0)
    if dtype == np.uint8:
        return np.clip(np.rint(r), 0, 255).astype(np.uint8)
    if dtype == np.uint16:
        return np.clip(np.rint(r), 0, 65535).astype(np.uint16)
    return r.astype(np.float32)


class ImageDoc:
    MAX_UNDO = 12

    def __init__(self, data, name="Untitled", rgb=False, pixel_size=1.0, unit="px", path=None):
        a = np.asarray(data)
        if a.ndim == 2:
            a = a[None, None]
        elif a.ndim == 3:
            a = a[:, None]
        if a.ndim != 4:
            raise ValueError("image data must be 2D, 3D or (F, C, Y, X)")
        self.data = np.ascontiguousarray(normalize_dtype(a))
        self.rgb = bool(rgb) and self.data.shape[1] == 3 and self.data.dtype == np.uint8
        self.name = name
        self.path = path
        self.pixel_size = float(pixel_size) if pixel_size and pixel_size > 0 else 1.0
        self.unit = unit or "px"
        self.frame = 0
        self.channel = 0
        self.composite = True
        self.rois = []
        self.active_roi = None
        self.overlays = {}      # frame -> RGBA uint8 (Y, X, 4)
        self.labels = {}        # frame -> [(x, y, text)]
        self.threshold = None   # (lo, hi) inclusive, on the active gray plane
        self.scale_bar = None
        self.undo_stack = []
        self.redo_stack = []
        self.modified = False
        self._init_display()

    # ---- geometry -----------------------------------------------------
    @property
    def F(self):
        return self.data.shape[0]

    @property
    def C(self):
        return self.data.shape[1]

    @property
    def H(self):
        return self.data.shape[2]

    @property
    def W(self):
        return self.data.shape[3]

    @property
    def dtype_max(self):
        return {np.dtype(np.uint8): 255.0, np.dtype(np.uint16): 65535.0}.get(self.data.dtype)

    def type_label(self):
        if self.rgb:
            return "RGB"
        return {np.dtype(np.uint8): "8-bit", np.dtype(np.uint16): "16-bit"}.get(self.data.dtype, "32-bit")

    def channel_names(self):
        return ["R", "G", "B"] if self.rgb else [f"C{i + 1}" for i in range(self.C)]

    # ---- pixel access -------------------------------------------------
    def plane(self, f=None, c=None):
        return self.data[self.frame if f is None else f, self.channel if c is None else c]

    def gray(self, f=None):
        """Plane used for thresholding and measuring (RGB -> mean of channels)."""
        f = self.frame if f is None else f
        if self.rgb:
            return self.data[f].mean(axis=0, dtype=np.float32)
        return self.data[f, self.channel]

    def threshold_mask(self, f=None):
        if self.threshold is None:
            return None
        g = self.gray(f)
        lo, hi = self.threshold
        return (g >= lo) & (g <= hi)

    # ---- display ------------------------------------------------------
    def auto_range(self, c):
        if self.data.dtype == np.uint8:
            return (0.0, 255.0)
        ch = self.data[:, c]
        lo, hi = float(ch.min()), float(ch.max())
        return (lo, hi if hi > lo else lo + 1.0)

    def _init_display(self):
        if self.rgb:
            self.luts = ["red", "green", "blue"]
            self.ranges = [(0.0, 255.0)] * 3
        else:
            self.luts = (["grays"] if self.C == 1 else
                         [DEFAULT_CHANNEL_LUTS[i % 7] for i in range(self.C)])
            self.ranges = [self.auto_range(c) for c in range(self.C)]
        self.channel = min(self.channel, self.C - 1)
        self.frame = min(self.frame, self.F - 1)

    @staticmethod
    def _to_index(plane, lo, hi):
        if hi <= lo:
            hi = lo + 1.0
        if plane.dtype == np.uint8 and lo == 0 and hi == 255:
            return plane
        return np.clip((plane.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)

    def render(self, f=None):
        """Return the displayed image as uint8 (Y, X, 3)."""
        f = self.frame if f is None else f
        if self.rgb:
            lo, hi = self.ranges[0]
            img = np.ascontiguousarray(self.data[f].transpose(1, 2, 0))
            return img if (lo, hi) == (0.0, 255.0) else self._to_index(img, lo, hi)
        chans = range(self.C) if (self.composite and self.C > 1) else [self.channel]
        acc = np.zeros((self.H, self.W, 3), np.uint16)
        for c in chans:
            acc += get_lut(self.luts[c])[self._to_index(self.data[f, c], *self.ranges[c])]
        return np.minimum(acc, 255).astype(np.uint8)

    # ---- undo ---------------------------------------------------------
    def _state(self):
        return dict(data=self.data, rgb=self.rgb, luts=list(self.luts), ranges=list(self.ranges),
                    threshold=self.threshold, pixel_size=self.pixel_size, unit=self.unit,
                    overlays=dict(self.overlays), labels=dict(self.labels), rois=list(self.rois),
                    active_roi=self.active_roi)

    def _restore(self, s):
        self.__dict__.update(s)
        self.channel = min(self.channel, self.C - 1)
        self.frame = min(self.frame, self.F - 1)

    def push_undo(self):
        self.undo_stack.append(self._state())
        del self.undo_stack[:-self.MAX_UNDO]
        self.redo_stack.clear()
        self.modified = True

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self._state())
            self._restore(self.undo_stack.pop())
            return True
        return False

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self._state())
            self._restore(self.redo_stack.pop())
            return True
        return False

    # ---- modification -------------------------------------------------
    def set_data(self, data, rgb=None):
        old = self.data
        was_rgb = self.rgb
        self.data = np.ascontiguousarray(normalize_dtype(np.asarray(data)))
        if rgb is not None:
            self.rgb = bool(rgb)
        self.rgb = self.rgb and self.C == 3 and self.data.dtype == np.uint8
        if old.shape[1] != self.C or old.dtype != self.data.dtype or was_rgb != self.rgb:
            self._init_display()
        if old.shape[2:] != self.data.shape[2:]:
            self.overlays, self.labels = {}, {}
            self.active_roi = None
            self.threshold = None
        self.channel = min(self.channel, self.C - 1)
        self.frame = min(self.frame, self.F - 1)

    def copy(self, name=None, data=None):
        d = ImageDoc(self.data if data is None else data, name or self.name, self.rgb,
                     self.pixel_size, self.unit)
        if d.C == self.C and d.rgb == self.rgb and d.data.dtype == self.data.dtype:
            d.luts, d.ranges = list(self.luts), list(self.ranges)
        d.composite = self.composite
        d.channel = min(self.channel, d.C - 1)
        return d

    def frame_doc(self):
        """Single-frame shallow copy used for live previews."""
        d = self.copy(data=self.data[self.frame:self.frame + 1])
        d.threshold = self.threshold
        d.active_roi = self.active_roi
        return d
