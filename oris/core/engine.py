"""Operation registry and execution engine.

Every user-visible operation is an entry in ``OPS`` so that menus, parameter dialogs,
the macro recorder, scripts and batch processing all share one implementation."""
from __future__ import annotations

import inspect

import numpy as np
from skimage import transform

from . import analysis as an, filters as flt, measure as ms
from .image import ImageDoc, LUT_NAMES, cast_like
from .results import ResultsTable
from .roi import Roi


class OpError(Exception):
    """An error with a translatable message key."""

    def __init__(self, key, **kw):
        super().__init__(key)
        self.key, self.kw = key, kw


class Context:
    """The set of open images. The GUI subclasses this to keep tabs in sync."""

    def __init__(self):
        self._docs, self._current = [], None

    @property
    def docs(self):
        return self._docs

    @property
    def current(self):
        return self._current

    def add(self, doc):
        self._docs.append(doc)
        self._current = doc

    def select(self, key):
        for i, d in enumerate(self.docs):
            if key == i or key == d.name:
                self._current = d
                return d
        raise OpError("err.no_such_image", name=str(key))

    def by_name(self, name):
        for d in self.docs:
            if d.name == name:
                return d
        raise OpError("err.no_such_image", name=str(name))


def P(name, typ, default=None, lo=None, hi=None, choices=None):
    return {"name": name, "type": typ, "default": default, "lo": lo, "hi": hi, "choices": choices}


class Op:
    def __init__(self, name, kind, func, params=()):
        self.name, self.kind, self.func, self.params = name, kind, func, list(params)

    def defaults(self):
        return {p["name"]: p["default"] for p in self.params}


OPS = {}


def reg(name, kind, func, *params):
    OPS[name] = Op(name, kind, func, params)


class Engine:
    TABLES = ["results", "particles", "summary", "cells", "gel", "coloc", "fluor", "wound"]

    def __init__(self):
        self.tables = {k: ResultsTable() for k in self.TABLES}
        self.whole_stack = True
        self.last_table = "results"

    def table(self, key):
        self.last_table = key
        return self.tables[key]

    def run(self, ctx, name, /, **params):
        if name not in OPS:
            raise OpError("err.unknown_op", name=name)
        op = OPS[name]
        p = op.defaults()
        for k in params:
            if k not in p:
                raise OpError("err.unknown_param", name=f"{name}.{k}")
        p.update(params)
        doc = ctx.current
        if doc is None:
            raise OpError("err.no_image")
        if op.kind == "plane":
            return self._apply(doc, op.func, p, binary=False)
        if op.kind == "binary":
            return self._apply(doc, op.func, p, binary=True)
        return op.func(self, ctx, doc, **p)

    def _apply(self, doc, func, p, binary):
        frames = range(doc.F) if self.whole_stack else [doc.frame]
        chans = range(doc.C) if doc.rgb else [doc.channel]
        kw = dict(p)
        if "_max" in inspect.signature(func).parameters:
            kw["_max"] = doc.dtype_max
        roi = doc.active_roi
        mask = roi.mask((doc.H, doc.W)) if roi is not None and roi.is_area else None
        out = doc.data.copy()
        for f in frames:
            for c in chans:
                a = doc.data[f, c]
                if binary:
                    if not flt.is_binary(a):
                        raise OpError("err.need_binary")
                    new = func(a > 0, **kw).astype(doc.data.dtype) * 255
                else:
                    new = cast_like(func(a.astype(np.float32), **kw), doc.data.dtype)
                out[f, c] = new if mask is None else np.where(mask, new, a)
        doc.push_undo()
        doc.data = out


# ---------------------------------------------------------------------------
# plane and binary operations
# ---------------------------------------------------------------------------
reg("smooth", "plane", flt.smooth)
reg("sharpen", "plane", flt.sharpen)
reg("find_edges", "plane", flt.find_edges)
reg("gaussian", "plane", flt.gaussian, P("sigma", "float", 2.0, 0.1, 200.0))
reg("median", "plane", flt.median, P("radius", "int", 2, 1, 50))
reg("mean", "plane", flt.mean, P("radius", "int", 2, 1, 200))
reg("minimum", "plane", flt.minimum, P("radius", "int", 1, 1, 50))
reg("maximum", "plane", flt.maximum, P("radius", "int", 1, 1, 50))
reg("variance", "plane", flt.variance, P("radius", "int", 2, 1, 100))
reg("unsharp", "plane", flt.unsharp, P("sigma", "float", 1.0, 0.1, 100.0), P("amount", "float", 0.6, 0.05, 0.95))
reg("bandpass", "plane", flt.bandpass, P("large", "float", 40.0, 1.0, 1000.0), P("small", "float", 3.0, 0.0, 100.0))
reg("subtract_background", "plane", flt.subtract_background,
    P("radius", "float", 50.0, 1.0, 1000.0), P("light_background", "bool", False))
reg("enhance_contrast", "plane", flt.enhance_contrast, P("saturated", "float", 0.35, 0.0, 20.0))
reg("equalize", "plane", flt.equalize)
reg("clahe", "plane", flt.clahe, P("clip_limit", "float", 0.01, 0.001, 0.2))
reg("invert", "plane", flt.invert)
reg("add", "plane", flt.add, P("value", "float", 25.0, -1e6, 1e6))
reg("subtract", "plane", flt.subtract, P("value", "float", 25.0, -1e6, 1e6))
reg("multiply", "plane", flt.multiply, P("value", "float", 1.25, -1e6, 1e6))
reg("divide", "plane", flt.divide, P("value", "float", 1.25, 1e-6, 1e6))
reg("gamma", "plane", flt.gamma, P("value", "float", 0.5, 0.05, 10.0))
reg("log", "plane", flt.log)
reg("sqrt", "plane", flt.sqrt)
reg("distance_map", "plane", flt.distance_map)
reg("erode", "binary", flt.erode, P("iterations", "int", 1, 1, 100))
reg("dilate", "binary", flt.dilate, P("iterations", "int", 1, 1, 100))
reg("open", "binary", flt.open_, P("iterations", "int", 1, 1, 100))
reg("close", "binary", flt.close_, P("iterations", "int", 1, 1, 100))
reg("fill_holes", "binary", flt.fill_holes)
reg("outline", "binary", flt.outline)
reg("skeletonize", "binary", flt.skeletonize)
reg("watershed", "binary", flt.watershed, P("tolerance", "float", 1.0, 0.1, 50.0))


# ---------------------------------------------------------------------------
# type conversion
# ---------------------------------------------------------------------------
def _gray_stack(doc):
    """(F, C', Y, X) float32 with RGB collapsed to one gray channel."""
    if doc.rgb:
        return doc.data.mean(axis=1, dtype=np.float32)[:, None]
    return doc.data.astype(np.float32)


def _to_8bit(eng, ctx, doc):
    if doc.data.dtype == np.uint8 and not doc.rgb:
        return
    g = _gray_stack(doc)
    if not doc.rgb:
        for c in range(doc.C):
            lo, hi = doc.ranges[c]
            g[:, c] = (g[:, c] - lo) * (255.0 / max(hi - lo, 1e-12))
    doc.push_undo()
    doc.set_data(cast_like(g, np.dtype(np.uint8)), rgb=False)


def _to_16bit(eng, ctx, doc):
    if doc.data.dtype == np.uint16:
        return
    g = _gray_stack(doc)
    if doc.data.dtype == np.float32:
        lo, hi = float(g.min()), float(g.max())
        g = (g - lo) * (65535.0 / max(hi - lo, 1e-12))
    doc.push_undo()
    doc.set_data(cast_like(g, np.dtype(np.uint16)), rgb=False)


def _to_32bit(eng, ctx, doc):
    if doc.data.dtype == np.float32:
        return
    g = _gray_stack(doc)
    doc.push_undo()
    doc.set_data(g, rgb=False)


def _to_rgb(eng, ctx, doc):
    if doc.rgb:
        return
    out = np.stack([doc.render(f).transpose(2, 0, 1) for f in range(doc.F)])
    doc.push_undo()
    doc.set_data(out, rgb=True)


reg("to_8bit", "doc", _to_8bit)
reg("to_16bit", "doc", _to_16bit)
reg("to_32bit", "doc", _to_32bit)
reg("to_rgb", "doc", _to_rgb)


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------
def _area_roi(doc):
    if doc.active_roi is None or not doc.active_roi.is_area:
        raise OpError("err.need_area_roi")
    return doc.active_roi


def _roi_box(doc):
    x0, y0, x1, y1 = (int(round(v)) for v in _area_roi(doc).bounds())
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, doc.W), min(y1, doc.H)
    if x1 - x0 < 1 or y1 - y0 < 1:
        raise OpError("err.need_area_roi")
    return x0, y0, x1, y1


def _crop(eng, ctx, doc):
    x0, y0, x1, y1 = _roi_box(doc)
    doc.push_undo()
    doc.rois = [r.move(-x0, -y0) for r in doc.rois]
    doc.set_data(doc.data[:, :, y0:y1, x0:x1])
    doc.active_roi = None


def _duplicate(eng, ctx, doc, whole_stack=True):
    data = doc.data if whole_stack else doc.data[doc.frame:doc.frame + 1]
    roi = None
    if doc.active_roi is not None and doc.active_roi.is_area:
        x0, y0, x1, y1 = _roi_box(doc)
        data = data[:, :, y0:y1, x0:x1]
        roi = doc.active_roi.move(-x0, -y0)
    new = doc.copy(name=_stem(doc.name) + "-copy", data=data.copy())
    if roi is not None and roi.kind != "rect":
        new.active_roi = roi
    ctx.add(new)
    return new


def _stem(name):
    return name.rsplit(".", 1)[0] if "." in name[-6:] else name


def _geom(fn):
    def op(eng, ctx, doc, **p):
        doc.push_undo()
        doc.rois = []
        doc.active_roi = None
        doc.overlays, doc.labels = {}, {}
        doc.set_data(fn(doc, **p))
    return op


def _rotate(doc, angle=15.0, enlarge=False, interpolation="bilinear"):
    order = {"nearest": 0, "bilinear": 1, "bicubic": 3}[interpolation]
    planes = [[transform.rotate(doc.data[f, c].astype(np.float32), angle, resize=enlarge, order=order,
                                preserve_range=True) for c in range(doc.C)] for f in range(doc.F)]
    return cast_like(np.array(planes), doc.data.dtype)


def _scale(doc, factor=0.5, interpolation="bilinear"):
    order = {"nearest": 0, "bilinear": 1, "bicubic": 3}[interpolation]
    H, W = max(1, int(round(doc.H * factor))), max(1, int(round(doc.W * factor)))
    planes = [[transform.resize(doc.data[f, c].astype(np.float32), (H, W), order=order, preserve_range=True,
                                anti_aliasing=factor < 1 and order > 0) for c in range(doc.C)]
              for f in range(doc.F)]
    doc.pixel_size /= factor
    return cast_like(np.array(planes), doc.data.dtype)


reg("crop", "doc", _crop)
reg("duplicate", "doc", _duplicate, P("whole_stack", "bool", True))
reg("flip_horizontal", "doc", _geom(lambda d: d.data[:, :, :, ::-1]))
reg("flip_vertical", "doc", _geom(lambda d: d.data[:, :, ::-1, :]))
reg("rotate_right", "doc", _geom(lambda d: np.rot90(d.data, -1, (2, 3))))
reg("rotate_left", "doc", _geom(lambda d: np.rot90(d.data, 1, (2, 3))))
reg("rotate", "doc", _geom(_rotate), P("angle", "float", 15.0, -360.0, 360.0), P("enlarge", "bool", False),
    P("interpolation", "choice", "bilinear", choices=["nearest", "bilinear", "bicubic"]))
reg("scale", "doc", _geom(_scale), P("factor", "float", 0.5, 0.01, 20.0),
    P("interpolation", "choice", "bilinear", choices=["nearest", "bilinear", "bicubic"]))


def _fill(value_inside):
    def op(eng, ctx, doc):
        mask = _area_roi(doc).mask((doc.H, doc.W))
        if not value_inside:
            mask = ~mask
        frames = range(doc.F) if eng.whole_stack else [doc.frame]
        out = doc.data.copy()
        for f in frames:
            out[f][:, mask] = 0
        doc.push_undo()
        doc.data = out
    return op


reg("clear", "doc", _fill(True))
reg("clear_outside", "doc", _fill(False))


# ---------------------------------------------------------------------------
# stacks and channels
# ---------------------------------------------------------------------------
def _z_project(eng, ctx, doc, method="max"):
    fn = {"max": np.max, "min": np.min, "mean": np.mean, "sum": np.sum, "sd": np.std, "median": np.median}[method]
    r = fn(doc.data.astype(np.float32), axis=0)
    data = r if method in ("sum", "sd") else cast_like(r, doc.data.dtype)
    new = doc.copy(name=f"{method.upper()}_{_stem(doc.name)}", data=data[None])
    ctx.add(new)
    return new


def _split_channels(eng, ctx, doc):
    if doc.C < 2:
        raise OpError("err.need_multichannel")
    out = []
    for c, cname in enumerate(doc.channel_names()):
        new = ImageDoc(doc.data[:, c:c + 1].copy(), f"{_stem(doc.name)}-{cname}", pixel_size=doc.pixel_size,
                       unit=doc.unit)
        new.luts = ["grays"] if doc.rgb else [doc.luts[c]]
        if not doc.rgb:
            new.ranges = [doc.ranges[c]]
        out.append(new)
    for new in out:
        ctx.add(new)
    return out


def _merge_channels(eng, ctx, doc, c1="", c2="", c3="", c4=""):
    names = [n for n in (c1, c2, c3, c4) if n and n != "none"]
    docs = [ctx.by_name(n) for n in names]
    if len(docs) < 2:
        raise OpError("err.need_two_images")
    ref = docs[0]
    for d in docs:
        if d.data.shape[0] != ref.data.shape[0] or d.data.shape[2:] != ref.data.shape[2:] \
                or d.data.dtype != ref.data.dtype:
            raise OpError("err.size_mismatch")
    data = np.concatenate([cast_like(_gray_stack(d), d.data.dtype) if d.rgb else d.data[:, d.channel:d.channel + 1] for d in docs], axis=1)
    new = ImageDoc(data, "Merged", pixel_size=ref.pixel_size, unit=ref.unit)
    new.ranges = [d.ranges[d.channel] if not d.rgb else (0.0, 255.0) for d in docs]
    ctx.add(new)
    return new


def _images_to_stack(eng, ctx, doc):
    docs = [d for d in ctx.docs if d.data.shape[1:] == doc.data.shape[1:] and d.data.dtype == doc.data.dtype
            and d.rgb == doc.rgb]
    if len(docs) < 2:
        raise OpError("err.need_two_images")
    new = doc.copy(name="Stack", data=np.concatenate([d.data for d in docs]))
    ctx.add(new)
    return new


def _stack_to_images(eng, ctx, doc):
    if doc.F < 2:
        raise OpError("err.need_stack")
    out = [doc.copy(name=f"{_stem(doc.name)}-{f + 1:03d}", data=doc.data[f:f + 1].copy()) for f in range(doc.F)]
    for d in out:
        ctx.add(d)
    return out


CALC = {
    "add": lambda a, b: a + b, "subtract": lambda a, b: a - b, "multiply": lambda a, b: a * b,
    "divide": lambda a, b: np.divide(a, b, out=np.zeros_like(a), where=b != 0),
    "difference": lambda a, b: np.abs(a - b), "average": lambda a, b: (a + b) / 2,
    "min": np.minimum, "max": np.maximum,
    "and": lambda a, b: np.where((a > 0) & (b > 0), np.maximum(a, b), 0),
    "or": lambda a, b: np.maximum(a, b),
    "xor": lambda a, b: np.where((a > 0) ^ (b > 0), np.maximum(a, b), 0),
}


def _image_calculator(eng, ctx, doc, image1="", image2="", operation="subtract", float_result=False):
    a, b = ctx.by_name(image1 or doc.name), ctx.by_name(image2 or doc.name)
    if a.data.shape[1:] != b.data.shape[1:] or (a.F != b.F and b.F != 1):
        raise OpError("err.size_mismatch")
    r = CALC[operation](a.data.astype(np.float32), b.data.astype(np.float32))
    data = r.astype(np.float32) if float_result else cast_like(r, a.data.dtype)
    new = ImageDoc(data, f"Result of {_stem(a.name)}", rgb=a.rgb and not float_result,
                   pixel_size=a.pixel_size, unit=a.unit)
    ctx.add(new)
    return new


reg("z_project", "doc", _z_project, P("method", "choice", "max", choices=["max", "min", "mean", "sum", "sd", "median"]))
reg("split_channels", "doc", _split_channels)
reg("merge_channels", "doc", _merge_channels, P("c1", "image", ""), P("c2", "image", ""),
    P("c3", "image_opt", "none"), P("c4", "image_opt", "none"))
reg("images_to_stack", "doc", _images_to_stack)
reg("stack_to_images", "doc", _stack_to_images)
reg("image_calculator", "doc", _image_calculator, P("image1", "image", ""),
    P("operation", "choice", "subtract", choices=list(CALC)), P("image2", "image", ""),
    P("float_result", "bool", False))


# ---------------------------------------------------------------------------
# display, calibration, threshold
# ---------------------------------------------------------------------------
def _set_scale(eng, ctx, doc, distance=1.0, known=1.0, unit="µm"):
    if distance <= 0 or known <= 0 or unit in ("", "px", "pixel"):
        doc.pixel_size, doc.unit = 1.0, "px"
    else:
        doc.pixel_size, doc.unit = known / distance, ("µm" if unit in ("um", "micron") else unit)


def _set_lut(eng, ctx, doc, name="grays"):
    if doc.rgb:
        raise OpError("err.not_for_rgb")
    doc.luts[doc.channel] = name


def _set_range(eng, ctx, doc, lower=0.0, upper=255.0):
    for c in (range(3) if doc.rgb else [doc.channel]):
        doc.ranges[c] = (float(lower), float(max(upper, lower + 1e-6)))


def _auto_contrast(eng, ctx, doc, saturated=0.35):
    g = doc.data[doc.frame] if doc.rgb else doc.plane()
    lo, hi = np.percentile(g, [saturated / 2, 100 - saturated / 2])
    _set_range(eng, ctx, doc, float(lo), float(hi if hi > lo else lo + 1))


def _reset_contrast(eng, ctx, doc):
    for c in (range(3) if doc.rgb else [doc.channel]):
        doc.ranges[c] = doc.auto_range(c)


def _apply_contrast(eng, ctx, doc):
    """Bake the display range into the pixel values."""
    if doc.data.dtype == np.float32:
        raise OpError("err.not_for_32bit")
    top = doc.dtype_max
    out = doc.data.copy()
    for c in (range(3) if doc.rgb else [doc.channel]):
        lo, hi = doc.ranges[c]
        out[:, c] = cast_like((doc.data[:, c].astype(np.float32) - lo) * (top / max(hi - lo, 1e-12)), doc.data.dtype)
    doc.push_undo()
    doc.data = out
    for c in (range(3) if doc.rgb else [doc.channel]):
        doc.ranges[c] = (0.0, top)


def _set_threshold(eng, ctx, doc, method="otsu", background="auto", lower=0.0, upper=0.0):
    g = doc.gray()
    gmin, gmax = float(g.min()), float(g.max())
    if method == "manual":
        doc.threshold = (float(lower), float(upper))
        return doc.threshold
    t = flt.auto_threshold(g, method)
    dark = flt.is_dark_background(g, t) if background == "auto" else background == "dark"
    integer = doc.data.dtype != np.float32 and not doc.rgb
    if dark:
        doc.threshold = (float(np.floor(t) + 1) if integer else float(np.nextafter(np.float32(t), np.float32(np.inf))), gmax)
    else:
        doc.threshold = (gmin, float(np.floor(t)) if integer else float(t))
    return doc.threshold


def _clear_threshold(eng, ctx, doc):
    doc.threshold = None


def _foreground(doc, f):
    """Boolean foreground of frame ``f``: current threshold, or the image itself when binary."""
    g = doc.gray(f)
    if doc.threshold is not None:
        return doc.threshold_mask(f)
    if flt.is_binary(g):
        return g > 0
    raise OpError("err.need_threshold")


def _make_binary(eng, ctx, doc):
    out = np.zeros((doc.F, 1, doc.H, doc.W), np.uint8)
    for f in range(doc.F):
        g = doc.gray(f)
        if doc.threshold is not None:
            m = doc.threshold_mask(f)
        elif flt.is_binary(g):
            m = g > 0
        else:
            t = flt.auto_threshold(g)
            m = (g > t) if flt.is_dark_background(g, t) else (g <= t)
        out[f, 0] = m.astype(np.uint8) * 255
    doc.push_undo()
    doc.set_data(out, rgb=False)
    doc.threshold = None


def _scale_bar(eng, ctx, doc, length=0.0, thickness=4, color="white", position="lower_right", label=True):
    if length <= 0:
        doc.scale_bar = None
    else:
        doc.scale_bar = {"length": float(length), "thickness": int(thickness), "color": color,
                         "position": position, "label": bool(label)}


def _rename(eng, ctx, doc, name=""):
    if name.strip():
        doc.name = name.strip()


def _clear_overlay(eng, ctx, doc):
    doc.overlays, doc.labels = {}, {}


def _select(eng, ctx, doc, kind="rect", points=()):
    doc.active_roi = Roi(kind, points) if points else None


def _composite(eng, ctx, doc, on=True):
    doc.composite = bool(on)


reg("set_scale", "doc", _set_scale, P("distance", "float", 1.0, 0.0, 1e7), P("known", "float", 1.0, 0.0, 1e7),
    P("unit", "str", "µm"))
reg("set_lut", "doc", _set_lut, P("name", "choice", "grays", choices=LUT_NAMES))
reg("set_range", "doc", _set_range, P("lower", "float", 0.0, -1e9, 1e9), P("upper", "float", 255.0, -1e9, 1e9))
reg("auto_contrast", "doc", _auto_contrast, P("saturated", "float", 0.35, 0.0, 20.0))
reg("reset_contrast", "doc", _reset_contrast)
reg("apply_contrast", "doc", _apply_contrast)
reg("set_threshold", "doc", _set_threshold,
    P("method", "choice", "otsu", choices=flt.THRESHOLD_METHODS + ["manual"]),
    P("background", "choice", "auto", choices=["auto", "dark", "light"]),
    P("lower", "float", 0.0, -1e9, 1e9), P("upper", "float", 0.0, -1e9, 1e9))
reg("clear_threshold", "doc", _clear_threshold)
reg("make_binary", "doc", _make_binary)
reg("scale_bar", "doc", _scale_bar, P("length", "float", 100.0, 0.0, 1e7), P("thickness", "int", 4, 1, 200),
    P("color", "choice", "white", choices=["white", "black", "yellow"]),
    P("position", "choice", "lower_right", choices=["lower_right", "lower_left", "upper_right", "upper_left"]),
    P("label", "bool", True))
reg("rename", "doc", _rename, P("name", "str", ""))
reg("clear_overlay", "doc", _clear_overlay)
reg("select", "doc", _select, P("kind", "str", "rect"), P("points", "raw", ()))
reg("composite", "doc", _composite, P("on", "bool", True))


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------
def _frames(doc, all_frames):
    return range(doc.F) if all_frames else [doc.frame]


def _measure(eng, ctx, doc):
    rows = ms.measure_roi(doc, doc.active_roi)
    eng.table("results").extend(rows)
    return rows


def _measure_all(eng, ctx, doc):
    if not doc.rois:
        raise OpError("err.no_rois")
    rows = []
    for i, roi in enumerate(doc.rois):
        r = roi if roi.name else Roi(roi.kind, roi.pts, f"ROI{i + 1}", roi.cats)
        rows += ms.measure_roi(doc, r)
    eng.table("results").extend(rows)
    return rows


def _restrict(doc, mask):
    roi = doc.active_roi
    return mask & roi.mask(mask.shape) if roi is not None and roi.is_area else mask


def _annotate(doc, f, labels, rows, outlines=True):
    px = doc.pixel_size
    if outlines:
        doc.overlays[f] = ms.outline_overlay(labels)
        doc.labels[f] = [(r["X"] / px, r["Y"] / px, str(r["#"])) for r in rows[:3000]]


def _add_rois(doc, labels, prefix):
    for i, poly in enumerate(ms.label_polygons(labels)[:1000]):
        if len(poly) >= 3:
            doc.rois.append(Roi("polygon", poly, f"{prefix}{i + 1}"))


def _analyze_particles(eng, ctx, doc, min_size=0.0, max_size=0.0, min_circ=0.0, max_circ=1.0,
                       exclude_edges=False, include_holes=False, show_outlines=True,
                       add_to_manager=False, all_frames=False):
    total = 0
    for f in _frames(doc, all_frames):
        g = doc.gray(f)
        binary = _restrict(doc, _foreground(doc, f))
        labels, rows, summary = ms.analyze_particles(
            binary, g, include_holes=include_holes, px=doc.pixel_size, min_size=min_size, max_size=max_size,
            min_circ=min_circ, max_circ=max_circ, exclude_edges=exclude_edges)
        eng.table("summary").add({"Label": doc.name, "Frame": f + 1, **summary})
        eng.table("particles").extend({"Label": doc.name, "Frame": f + 1, **r} for r in rows)
        _annotate(doc, f, labels, rows, show_outlines)
        if add_to_manager:
            _add_rois(doc, labels, "P")
        total += summary["Count"]
    return {"count": total}


def _count_cells(eng, ctx, doc, sigma=1.5, bg_radius=0.0, method="otsu", background="auto", split=True,
                 tolerance=1.0, min_size=0.0, max_size=0.0, min_circ=0.0, exclude_edges=False,
                 add_to_manager=False, all_frames=False):
    total = 0
    for f in _frames(doc, all_frames):
        g = doc.gray(f)
        labels = an.segment_cells(g, sigma=sigma, bg_radius=bg_radius, method=method, background=background,
                                  split=split, tolerance=tolerance)
        roi = doc.active_roi
        if roi is not None and roi.is_area:
            labels = np.where(roi.mask(labels.shape), labels, 0)
        labels, rows, summary = ms.analyze_labels(labels, g, px=doc.pixel_size, min_size=min_size,
                                                  max_size=max_size, min_circ=min_circ, exclude_edges=exclude_edges)
        eng.table("summary").add({"Label": doc.name, "Frame": f + 1, **summary})
        eng.table("cells").extend({"Label": doc.name, "Frame": f + 1, **r} for r in rows)
        _annotate(doc, f, labels, rows)
        if add_to_manager:
            _add_rois(doc, labels, "Cell")
        total += summary["Count"]
    return {"count": total}


def _wound_healing(eng, ctx, doc, radius=8, sensitivity=1.0, min_area=1.0, keep_largest=False, all_frames=True):
    px = doc.pixel_size
    out, first = [], None
    for f in _frames(doc, all_frames):
        mask, st = an.detect_wound(doc.gray(f), radius=radius, sensitivity=sensitivity, min_area=min_area,
                                   keep_largest=keep_largest)
        area = st["area"] * px * px
        if first is None:
            first = area
        row = {"Label": doc.name, "Frame": f + 1, "Wound Area": area, "%Area": st["percent"],
               "Mean Width": st["width"] * px,
               "Closure %": 100.0 * (first - area) / first if first else 0.0}
        doc.overlays[f] = ms.mask_overlay(mask)
        doc.labels.pop(f, None)
        out.append(row)
    eng.table("wound").extend(out)
    return out


def _channel_index(doc, ch):
    names = doc.channel_names()
    if isinstance(ch, str):
        if ch in names:
            return names.index(ch)
        raise OpError("err.bad_channel")
    if not 0 <= int(ch) < doc.C:
        raise OpError("err.bad_channel")
    return int(ch)


def _colocalization(eng, ctx, doc, ch1=0, ch2=1, threshold="costes", t1=0.0, t2=0.0):
    if doc.C < 2:
        raise OpError("err.need_multichannel")
    a, b = _channel_index(doc, ch1), _channel_index(doc, ch2)
    roi = doc.active_roi
    mask = roi.mask((doc.H, doc.W)) if roi is not None and roi.is_area else None
    try:
        r = an.colocalization(doc.data[doc.frame, a], doc.data[doc.frame, b], mask, threshold, t1, t2)
    except ValueError:
        raise OpError("err.roi_too_small")
    names = doc.channel_names()
    row = {"Label": doc.name, "Ch1": names[a], "Ch2": names[b],
           **{k: v for k, v in r.items() if not k.startswith("_")}}
    eng.table("coloc").add(row)
    return r


def _fluorescence(eng, ctx, doc, background="auto", value=0.0, all_channels=True):
    """CTCF for every ROI in the manager (or the active selection / whole image)."""
    rois = [r for r in doc.rois if r.is_area]
    if not rois and doc.active_roi is not None and doc.active_roi.is_area:
        rois = [doc.active_roi]
    names = doc.channel_names()
    chans = range(doc.C) if (all_channels and not doc.rgb) or doc.rgb else [doc.channel]
    bg_roi = next((r for r in rois if r.name.lower() in ("bg", "background", "bkgd")), None)
    if background == "roi":
        if bg_roi is None:
            raise OpError("err.need_bg_roi")
    rows = []
    for c in chans:
        plane = doc.data[doc.frame, c]
        if background == "roi":
            bg = float(plane[bg_roi.mask(plane.shape)].mean())
        elif background == "auto":
            bg = an.auto_background(plane)
        else:
            bg = float(value)
        targets = [r for r in rois if r is not bg_roi] or [None]
        for i, roi in enumerate(targets):
            mask = np.ones(plane.shape, bool) if roi is None else roi.mask(plane.shape)
            name = "" if roi is None else (roi.name or f"ROI{i + 1}")
            rows.append({"Label": doc.name, "ROI": name, "Ch": names[c], **an.ctcf(plane, mask, bg, doc.pixel_size)})
    eng.table("fluor").extend(rows)
    return rows


def _gel(eng, ctx, doc, strips=(), axis="row", lanes=0, mode="auto", polarity="auto", bg_radius=0,
         prominence=5.0, control="", reference=1):
    """Quantify band strips. ``strips`` is [(name, (x0, y0, x1, y1)), ...]."""
    if not strips:
        raise OpError("err.no_strips")
    g = doc.gray()
    res = {}
    for name, rect in strips:
        try:
            res[name] = an.analyze_strip(g, rect, axis=axis, lanes=lanes, mode=mode, polarity=polarity,
                                         bg_radius=bg_radius, prominence=prominence, vmax=doc.dtype_max)
        except ValueError:
            raise OpError("err.roi_too_small")
    ctrl = res.get(control)
    rows = []
    order = ([control] if ctrl is not None else []) + [n for n in res if n != control or ctrl is None]
    for name in order:
        r = res[name]
        norm = ctrl is not None and name != control and len(ctrl["bands"]) == len(r["bands"]) and r["bands"]
        ratios = []
        if norm:
            ratios = [b["area"] / c["area"] if c["area"] > 0 else float("nan")
                      for b, c in zip(r["bands"], ctrl["bands"])]
            ref = ratios[min(max(int(reference), 1), len(ratios)) - 1]
        for i, b in enumerate(r["bands"]):
            row = {"Label": doc.name, "Strip": name, "Band": b["index"],
                   "Position": (b["peak"] + r["offset"]) * doc.pixel_size, "Area": b["area"],
                   "Percent": b["percent"]}
            if norm:
                row["Control"] = control
                row["Ratio"] = ratios[i]
                row["Fold change"] = ratios[i] / ref if ref else float("nan")
            rows.append(row)
    eng.table("gel").extend(rows)
    return res


reg("measure", "doc", _measure)
reg("measure_all", "doc", _measure_all)
reg("analyze_particles", "doc", _analyze_particles,
    P("min_size", "float", 0.0, 0.0, 1e12), P("max_size", "float", 0.0, 0.0, 1e12),
    P("min_circ", "float", 0.0, 0.0, 1.0), P("max_circ", "float", 1.0, 0.0, 1.0),
    P("exclude_edges", "bool", False), P("include_holes", "bool", False), P("show_outlines", "bool", True),
    P("add_to_manager", "bool", False), P("all_frames", "bool", False))
reg("count_cells", "doc", _count_cells,
    P("sigma", "float", 1.5, 0.0, 50.0), P("bg_radius", "float", 0.0, 0.0, 1000.0),
    P("method", "choice", "otsu", choices=flt.THRESHOLD_METHODS),
    P("background", "choice", "auto", choices=["auto", "dark", "light"]),
    P("split", "bool", True), P("tolerance", "float", 1.0, 0.1, 50.0),
    P("min_size", "float", 0.0, 0.0, 1e12), P("max_size", "float", 0.0, 0.0, 1e12),
    P("min_circ", "float", 0.0, 0.0, 1.0), P("exclude_edges", "bool", False),
    P("add_to_manager", "bool", False), P("all_frames", "bool", False))
reg("wound_healing", "doc", _wound_healing,
    P("radius", "int", 8, 2, 100), P("sensitivity", "float", 1.0, 0.1, 5.0),
    P("min_area", "float", 1.0, 0.0, 50.0), P("keep_largest", "bool", False), P("all_frames", "bool", True))
reg("colocalization", "doc", _colocalization, P("ch1", "channel", 0), P("ch2", "channel", 1),
    P("threshold", "choice", "costes", choices=["costes", "otsu", "manual", "none"]),
    P("t1", "float", 0.0, -1e9, 1e9), P("t2", "float", 0.0, -1e9, 1e9))
reg("fluorescence", "doc", _fluorescence, P("background", "choice", "auto", choices=["auto", "roi", "value"]),
    P("value", "float", 0.0, -1e9, 1e9), P("all_channels", "bool", True))
reg("gel", "doc", _gel, P("strips", "raw", ()), P("axis", "choice", "row", choices=["row", "lane"]),
    P("lanes", "int", 0, 0, 200), P("mode", "choice", "auto", choices=["auto", "even"]),
    P("polarity", "choice", "auto", choices=["auto", "dark", "light"]), P("bg_radius", "int", 0, 0, 5000),
    P("prominence", "float", 5.0, 0.1, 100.0), P("control", "str", ""), P("reference", "int", 1, 1, 200))


# ---------------------------------------------------------------------------
# scripting
# ---------------------------------------------------------------------------
def format_call(name, params):
    """Render an operation as a line of script (all given parameters are written out)."""
    known = OPS[name].defaults()
    args = "".join(f", {k}={v!r}" for k, v in params.items() if k in known)
    return f'run("{name}"{args})'


def script_namespace(engine, ctx, log=print):
    """Names available to user scripts (macros)."""
    from . import io

    def run(name, /, **params):
        return engine.run(ctx, name, **params)

    def open_image(path):
        doc = io.load_image(path)
        ctx.add(doc)
        return doc

    def save_image(path):
        io.save_image(ctx.current, path)

    def roi(kind=None, points=()):
        ctx.current.active_roi = Roi(kind, points) if kind and points else None

    return {"run": run, "open_image": open_image, "save_image": save_image, "roi": roi,
            "select_image": ctx.select, "image": lambda: ctx.current, "table": lambda key="results": engine.tables[key],
            "log": log, "print": log, "np": np}


def run_script(engine, ctx, code, log=print):
    ns = script_namespace(engine, ctx, log)
    exec(compile(code, "<script>", "exec"), ns)
    return ns


def batch(engine, files, code, out_dir=None, progress=None, log=print):
    """Run a script on every file; optionally save the resulting image as TIFF."""
    import os
    from . import io
    done, failed = 0, []
    for i, path in enumerate(files):
        if progress and progress(i, len(files), path) is False:
            break
        ctx = Context()
        try:
            ctx.add(io.load_image(path))
            run_script(engine, ctx, code, log)
            if out_dir:
                stem = os.path.splitext(os.path.basename(path))[0]
                io.save_image(ctx.current, os.path.join(out_dir, stem + "_processed.tif"))
            done += 1
        except OpError as e:
            failed.append((path, e.key))
        except Exception as e:  # noqa: BLE001 - report and continue with the next file
            failed.append((path, f"{type(e).__name__}: {e}"))
    return done, failed
