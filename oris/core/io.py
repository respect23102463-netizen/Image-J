"""Reading and writing image files."""
from __future__ import annotations

import os

import numpy as np
import tifffile
from PIL import Image, ImageOps

from .image import ImageDoc

READ_EXT = (".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")
MICRON = ("micron", "um", "\\u00B5m", "µm", "μm")


def _load_tiff(path):
    with tifffile.TiffFile(path) as tif:
        s = tif.series[0]
        arr = s.asarray()
        ax = list(s.axes)
        px, unit = 1.0, "px"
        try:
            page = tif.pages[0]
            ij = tif.imagej_metadata or {}
            xr = page.tags.get("XResolution")
            ru = page.tags.get("ResolutionUnit")
            res = None
            if xr is not None:
                num, den = xr.value
                res = num / den if num and den else None
            u = ij.get("unit")
            if u and res:
                px, unit = 1.0 / res, ("µm" if u in MICRON else str(u))
            elif res and ru is not None and int(ru.value) == 3:
                px, unit = 1e4 / res, "µm"
        except Exception:
            px, unit = 1.0, "px"
    if "Y" not in ax or "X" not in ax:
        raise ValueError("unsupported TIFF layout: " + "".join(ax))
    chan = "C" if "C" in ax else ("S" if "S" in ax else None)
    order = [i for i, a in enumerate(ax) if a not in (chan, "Y", "X")]
    if chan:
        order.append(ax.index(chan))
    order += [ax.index("Y"), ax.index("X")]
    arr = arr.transpose(order)
    H, W = arr.shape[-2:]
    arr = arr.reshape(-1, arr.shape[-3] if chan else 1, H, W)
    rgb = False
    if chan == "S":
        if arr.shape[1] == 4:
            arr = arr[:, :3]
        rgb = arr.shape[1] == 3 and arr.dtype == np.uint8
    return ImageDoc(arr, os.path.basename(path), rgb=rgb, pixel_size=px, unit=unit, path=path)


def _pil_frame(im):
    if im.mode in ("I;16", "I;16B", "I;16L", "I"):
        return np.clip(np.asarray(im), 0, 65535).astype(np.uint16), False
    if im.mode == "F":
        return np.asarray(im, np.float32), False
    if im.mode in ("L", "1", "LA"):
        return np.asarray(im.convert("L")), False
    return np.asarray(im.convert("RGB")).transpose(2, 0, 1), True


def _load_pil(path):
    im = Image.open(path)
    frames, rgb = [], False
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        fr = ImageOps.exif_transpose(im) if i == 0 and im.mode not in ("I;16", "I", "F") else im
        a, rgb = _pil_frame(fr)
        frames.append(a if a.ndim == 3 else a[None])
    return ImageDoc(np.stack(frames), os.path.basename(path), rgb=rgb, path=path)


def load_image(path):
    path = str(path)
    if os.path.splitext(path)[1].lower() in (".tif", ".tiff"):
        try:
            return _load_tiff(path)
        except Exception:
            return _load_pil(path)
    return _load_pil(path)


def load_sequence(paths):
    """Load several same-sized images as one stack."""
    docs = [load_image(p) for p in sorted(str(p) for p in paths)]
    if not docs:
        raise ValueError("no images")
    first = docs[0]
    for d in docs[1:]:
        if d.data.shape[1:] != first.data.shape[1:] or d.data.dtype != first.data.dtype:
            raise ValueError("size mismatch")
    out = first.copy(name=os.path.basename(os.path.dirname(first.path)) or "Stack",
                     data=np.concatenate([d.data for d in docs]))
    out.pixel_size, out.unit = first.pixel_size, first.unit
    return out


def save_image(doc, path):
    """Save as TIFF (full data: stacks, channels, bit depth, calibration) or PNG/JPG/BMP (current view)."""
    path = str(path)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".tif", ".tiff"):
        kw = {}
        if doc.unit != "px":
            kw["resolution"] = (1.0 / doc.pixel_size, 1.0 / doc.pixel_size)
        if doc.rgb:
            data = doc.data.transpose(0, 2, 3, 1)
            tifffile.imwrite(path, data[0] if doc.F == 1 else data, photometric="rgb", **kw)
        else:
            meta = {"axes": "ZCYX"}
            if doc.unit != "px":
                meta["unit"] = "micron" if doc.unit in MICRON else doc.unit
            tifffile.imwrite(path, doc.data, imagej=True, metadata=meta, **kw)
        return
    plain = (not doc.rgb and doc.C == 1 and doc.luts[0] == "grays" and ext == ".png"
             and doc.data.dtype in (np.uint8, np.uint16))
    if plain:
        Image.fromarray(doc.plane(c=0)).save(path)
    else:
        im = Image.fromarray(doc.render())
        im.save(path, quality=95) if ext in (".jpg", ".jpeg") else im.save(path)
