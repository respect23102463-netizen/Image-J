"""Numerical tests against images with known ground truth. Run: python -m pytest tests"""
import os
import sys
import warnings

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")

from oris.core import analysis as an, filters as flt, io, measure as ms, samples  # noqa: E402
from oris.core.engine import OPS, Context, Engine, OpError, batch, format_call, run_script  # noqa: E402
from oris.core.image import ImageDoc  # noqa: E402
from oris.core.roi import Roi  # noqa: E402


def ctx_with(doc):
    ctx = Context()
    ctx.add(doc)
    return Engine(), ctx


# ---- measurement ------------------------------------------------------------
def test_rect_measure_calibrated():
    d = ImageDoc(np.full((50, 60), 10, np.uint8), pixel_size=0.5, unit="um")
    r = ms.measure_roi(d, Roi("rect", [(5, 10), (45, 30)]))[0]
    assert r["Area"] == pytest.approx(40 * 20 * 0.25)
    assert r["Mean"] == 10 and r["IntDen"] == pytest.approx(2000) and r["RawIntDen"] == 8000
    assert r["Perim."] == pytest.approx(60) and r["Feret"] == pytest.approx(np.hypot(40, 20) * 0.5)
    assert r["MinFeret"] == pytest.approx(10) and r["X"] == pytest.approx(12.5) and r["Y"] == pytest.approx(10)


def test_ellipse_and_circle():
    d = ImageDoc(np.zeros((200, 200), np.uint8))
    r = ms.measure_roi(d, Roi("ellipse", [(20, 20), (180, 180)]))[0]
    assert r["Area"] == pytest.approx(np.pi * 80 ** 2, rel=0.01)
    assert r["Circ."] > 0.99 and r["AR"] == pytest.approx(1, abs=0.01)


def test_line_and_points():
    img = np.tile(np.arange(100, dtype=np.float32), (100, 1))
    d = ImageDoc(img)
    r = ms.measure_roi(d, Roi("line", [(0, 0), (30, 40)]))[0]
    assert r["Length"] == pytest.approx(50)
    x, y = ms.roi_profile(d, Roi("line", [(10.5, 50.5), (60.5, 50.5)]))
    assert y[0] == pytest.approx(10) and y[-1] == pytest.approx(60)
    rows = ms.measure_roi(d, Roi("point", [(5, 5), (70, 9)]))
    assert [r["Value"] for r in rows] == [5, 70]


def test_polygon_mask_matches_rect():
    poly = Roi("polygon", [(10, 10), (40, 10), (40, 30), (10, 30)])
    rect = Roi("rect", [(10, 10), (40, 30)])
    assert (poly.mask((50, 50)) == rect.mask((50, 50))).all()
    assert poly.contains(20, 20) and not poly.contains(45, 20)


def test_particles_count_and_filters():
    b = np.zeros((100, 200), bool)
    b[10:20, 10:20] = True          # 100 px
    b[40:60, 40:60] = True          # 400 px
    b[0:5, 100:110] = True          # touches edge
    b[45:55, 45:55] = False         # hole in the big one
    lab, rows, s = ms.analyze_particles(b)
    assert s["Count"] == 3 and sorted(r["Area"] for r in rows) == [50, 100, 300]
    lab, rows, s = ms.analyze_particles(b, include_holes=True, exclude_edges=True, min_size=150)
    assert s["Count"] == 1 and rows[0]["Area"] == 400
    lab, rows, s = ms.analyze_particles(b, px=0.5)
    assert sorted(r["Area"] for r in rows) == [12.5, 25, 75]


# ---- filters ----------------------------------------------------------------
def test_filters_preserve_type_and_shape():
    rng = np.random.default_rng(0)
    for dtype in (np.uint8, np.uint16, np.float32):
        for rgb in (False, True):
            if rgb and dtype != np.uint8:
                continue
            data = (rng.random((2, 3, 40, 50)) * 200).astype(dtype)
            for name, op in OPS.items():
                if op.kind != "plane":
                    continue
                eng, ctx = ctx_with(ImageDoc(data, rgb=rgb))
                eng.run(ctx, name)
                d = ctx.current
                assert d.data.shape == data.shape and d.data.dtype == dtype, name
                assert np.isfinite(d.data.astype(float)).all(), name
                assert d.undo() and (d.data == data).all(), name


def test_invert_and_math():
    eng, ctx = ctx_with(ImageDoc(np.array([[0, 100, 255]], np.uint8).repeat(3, 0)))
    eng.run(ctx, "invert")
    assert ctx.current.data[0, 0, 0].tolist() == [255, 155, 0]
    eng.run(ctx, "add", value=200)
    assert ctx.current.data.max() == 255          # clipped
    eng.run(ctx, "multiply", value=0.5)
    assert ctx.current.data[0, 0, 0].tolist() == [128, 128, 100]


def test_filter_respects_roi_and_stack_flag():
    data = np.full((3, 20, 20), 100, np.uint8)
    eng, ctx = ctx_with(ImageDoc(data))
    ctx.current.active_roi = Roi("rect", [(0, 0), (10, 10)])
    eng.whole_stack = False
    ctx.current.frame = 1
    eng.run(ctx, "add", value=50)
    d = ctx.current.data
    assert d[1, 0, 5, 5] == 150 and d[1, 0, 15, 15] == 100 and d[0, 0, 5, 5] == 100


def test_binary_ops():
    b = np.zeros((40, 40), np.uint8)
    b[10:30, 10:30] = 255
    b[18:22, 18:22] = 0
    eng, ctx = ctx_with(ImageDoc(b))
    eng.run(ctx, "fill_holes")
    assert ctx.current.data.sum() == 400 * 255
    eng.run(ctx, "erode")
    assert ctx.current.data.sum() == 18 * 18 * 255
    eng.run(ctx, "dilate")
    assert ctx.current.data.sum() == 400 * 255
    eng2, ctx2 = ctx_with(ImageDoc(np.arange(100, dtype=np.uint8).reshape(10, 10)))
    with pytest.raises(OpError):
        eng2.run(ctx2, "erode")


def test_watershed_splits_touching_discs():
    yy, xx = np.mgrid[:60, :90]
    b = ((xx - 30) ** 2 + (yy - 30) ** 2 < 15 ** 2) | ((xx - 55) ** 2 + (yy - 30) ** 2 < 15 ** 2)
    assert flt.split_labels(b).max() == 2
    assert ms.analyze_particles(flt.watershed(b))[2]["Count"] == 2


def test_threshold_and_make_binary():
    img = np.full((50, 50), 20, np.uint8)
    img[10:20, 10:20] = 200
    eng, ctx = ctx_with(ImageDoc(img))
    lo, hi = eng.run(ctx, "set_threshold", method="otsu")
    assert 20 < lo <= 200 and hi == 200
    assert ctx.current.threshold_mask().sum() == 100
    r = eng.run(ctx, "analyze_particles")
    assert r["count"] == 1 and eng.tables["particles"].rows[0]["Mean"] == 200
    eng.run(ctx, "make_binary")
    assert ctx.current.data.sum() == 100 * 255 and ctx.current.threshold is None
    # light background: dark objects become foreground
    eng, ctx = ctx_with(ImageDoc(255 - img))
    eng.run(ctx, "make_binary")
    assert ctx.current.data.sum() == 100 * 255


# ---- types, geometry, stacks ---------------------------------------------------
def test_type_conversions_roundtrip():
    rgb = np.zeros((1, 3, 10, 10), np.uint8)
    rgb[0, 0], rgb[0, 1], rgb[0, 2] = 30, 60, 90
    eng, ctx = ctx_with(ImageDoc(rgb, rgb=True))
    d = ctx.current
    eng.run(ctx, "to_8bit")
    assert d.C == 1 and not d.rgb and d.data[0, 0, 0, 0] == 60
    eng.run(ctx, "to_16bit")
    assert d.data.dtype == np.uint16 and d.data[0, 0, 0, 0] == 60
    eng.run(ctx, "to_32bit")
    assert d.data.dtype == np.float32
    eng.run(ctx, "to_rgb")
    assert d.rgb and d.data.shape == (1, 3, 10, 10)
    for _ in range(4):
        assert d.undo()
    assert d.rgb and (d.data == rgb).all()


def test_16bit_to_8bit_uses_display_range():
    eng, ctx = ctx_with(ImageDoc(np.array([[1000, 2000, 3000]], np.uint16)))
    assert ctx.current.ranges[0] == (1000.0, 3000.0)
    eng.run(ctx, "to_8bit")
    assert ctx.current.data[0, 0, 0].tolist() == [0, 128, 255]


def test_geometry():
    img = np.arange(6, dtype=np.uint8).reshape(2, 3)
    eng, ctx = ctx_with(ImageDoc(img))
    d = ctx.current
    eng.run(ctx, "rotate_right")
    assert d.data.shape[2:] == (3, 2) and (d.data[0, 0] == np.rot90(img, -1)).all()
    eng.run(ctx, "rotate_left")
    eng.run(ctx, "flip_horizontal")
    assert (d.data[0, 0] == img[:, ::-1]).all()
    eng, ctx = ctx_with(ImageDoc(np.zeros((100, 200), np.uint8), pixel_size=2.0, unit="um"))
    ctx.current.active_roi = Roi("rect", [(10, 20), (60, 50)])
    eng.run(ctx, "crop")
    assert ctx.current.data.shape[2:] == (30, 50) and ctx.current.active_roi is None
    eng.run(ctx, "scale", factor=0.5)
    assert ctx.current.data.shape[2:] == (15, 25) and ctx.current.pixel_size == 4.0
    assert ctx.current.undo() and ctx.current.undo()
    d = ctx.current                                   # undo restores pixels, calibration and selection
    assert d.data.shape[2:] == (100, 200) and d.pixel_size == 2.0 and d.active_roi is not None


def test_stacks_and_channels():
    f = samples.fluorescence()
    eng, ctx = ctx_with(f)
    parts = eng.run(ctx, "split_channels")
    assert len(parts) == 2 and parts[0].C == 1 and parts[0].luts == ["green"]
    merged = eng.run(ctx, "merge_channels", c1=parts[0].name, c2=parts[1].name)
    assert merged.C == 2 and (merged.data == f.data).all()
    w = samples.wound()
    eng, ctx = ctx_with(w)
    proj = eng.run(ctx, "z_project", method="max")
    assert proj.F == 1 and (proj.data[0, 0] == w.data[:, 0].max(0)).all()
    ctx.select(w.name)
    frames = eng.run(ctx, "stack_to_images")
    assert len(frames) == 3
    ctx.select(frames[0].name)
    eng2 = Engine()
    c2 = Context()
    for fr in frames:
        c2.add(fr)
    assert (eng2.run(c2, "images_to_stack").data == w.data).all()
    diff = eng.run(ctx, "image_calculator", image1=frames[0].name, image2=frames[0].name, operation="subtract")
    assert diff.data.max() == 0


def test_parameters_named_like_arguments():
    eng, ctx = ctx_with(samples.fluorescence())
    eng.run(ctx, "set_lut", name="cyan")
    eng.run(ctx, "rename", name="renamed")
    assert ctx.current.luts[0] == "cyan" and ctx.current.name == "renamed"
    run_script(eng, ctx, 'run("rename", name="again")')
    assert ctx.current.name == "again"
    with pytest.raises(OpError):
        eng.run(ctx, "gaussian", bogus=1)


def test_set_scale():
    eng, ctx = ctx_with(ImageDoc(np.zeros((10, 10), np.uint8)))
    eng.run(ctx, "set_scale", distance=200, known=100, unit="um")
    assert ctx.current.pixel_size == 0.5 and ctx.current.unit == "µm"
    assert ms.measure_roi(ctx.current)[0]["Area"] == 25


# ---- file formats -----------------------------------------------------------
def test_tiff_roundtrip(tmp_path):
    for doc in (samples.fluorescence(), samples.wound(), samples.blot()):
        p = tmp_path / (doc.name + ".tif")
        io.save_image(doc, p)
        back = io.load_image(p)
        assert back.data.shape == doc.data.shape and back.data.dtype == doc.data.dtype
        assert (back.data == doc.data).all()
        assert back.pixel_size == pytest.approx(doc.pixel_size, rel=1e-4) and back.unit == doc.unit
    rgb = ImageDoc((np.random.default_rng(0).random((1, 3, 20, 30)) * 255).astype(np.uint8), rgb=True)
    io.save_image(rgb, tmp_path / "rgb.tif")
    back = io.load_image(tmp_path / "rgb.tif")
    assert back.rgb and (back.data == rgb.data).all()
    io.save_image(rgb, tmp_path / "rgb.png")
    back = io.load_image(tmp_path / "rgb.png")
    assert back.rgb and (back.data == rgb.data).all()
    g16 = ImageDoc((np.arange(600).reshape(20, 30) * 100).astype(np.uint16))
    io.save_image(g16, tmp_path / "g16.png")
    assert (io.load_image(tmp_path / "g16.png").data == g16.data).all()
    io.save_image(samples.blot(), tmp_path / "b.jpg")
    assert io.load_image(tmp_path / "b.jpg").data.shape[2:] == (300, 560)
    seq = io.load_sequence([tmp_path / "rgb.png", tmp_path / "rgb.tif"])
    assert seq.F == 2


# ---- analysis modules against ground truth -------------------------------------
def test_western_blot_quantification():
    b = samples.blot()
    eng, ctx = ctx_with(b)
    res = eng.run(ctx, "gel", strips=[("target", (30, 75, 530, 115)), ("actin", (30, 185, 530, 225))],
                  lanes=6, control="actin", reference=1)
    assert len(res["target"]["bands"]) == 6 and res["target"]["dark_bands"]
    rows = [r for r in eng.tables["gel"].rows if r["Strip"] == "target"]
    fold = [r["Fold change"] for r in rows]
    assert np.allclose(fold, samples.BLOT_TARGET, atol=0.02)
    # automatic lane detection and even split agree
    for kw in ({"lanes": 0}, {"lanes": 6, "mode": "even"}):
        a = np.array([x["area"] for x in an.analyze_strip(b.gray(), (30, 75, 530, 115), **kw)["bands"]])
        assert len(a) == 6 and np.allclose(a / a[0], samples.BLOT_TARGET, atol=0.02)
    # inverted (bright bands on dark) gives the same answer
    a = np.array([x["area"] for x in an.analyze_strip(255 - b.gray(), (30, 75, 530, 115), lanes=6)["bands"]])
    assert np.allclose(a / a[0], samples.BLOT_TARGET, atol=0.02)


def test_cell_count():
    n = samples.nuclei()
    eng, ctx = ctx_with(n)
    assert eng.run(ctx, "count_cells", split=False)["count"] < samples.NUCLEI_COUNT
    assert eng.run(ctx, "count_cells")["count"] == samples.NUCLEI_COUNT
    assert 0 in n.overlays and len(n.labels[0]) == samples.NUCLEI_COUNT
    eng.run(ctx, "count_cells", add_to_manager=True)
    assert len(n.rois) == samples.NUCLEI_COUNT
    # same answer on an inverted (bright-field like) image
    eng, ctx = ctx_with(ImageDoc(255 - n.data))
    assert eng.run(ctx, "count_cells")["count"] == samples.NUCLEI_COUNT


def test_colocalization():
    f = samples.fluorescence()
    eng, ctx = ctx_with(f)
    r = eng.run(ctx, "colocalization")
    assert 0.4 < r["Pearson r"] < 0.7 and 0.4 < r["M1"] < 0.85 and 0.4 < r["M2"] < 0.85
    same = an.colocalization(f.data[0, 0], f.data[0, 0], threshold="otsu")
    assert same["Pearson r"] == pytest.approx(1) and same["M1"] == pytest.approx(1)
    rng = np.random.default_rng(0)
    rnd = an.colocalization(rng.random((200, 200)), rng.random((200, 200)))
    assert abs(rnd["Pearson r"]) < 0.03 and rnd["M1"] < 0.05
    a = np.zeros((100, 100))
    b = np.zeros((100, 100))
    a[:50], b[50:] = 100, 100       # mutually exclusive
    ex = an.colocalization(a, b, threshold="none")
    assert ex["Pearson r"] == pytest.approx(-1) and ex["M1"] == 0 and ex["M2"] == 0


def test_ctcf():
    img = np.full((100, 100), 10.0, np.float32)
    img[20:40, 20:40] = 110
    eng, ctx = ctx_with(ImageDoc(img))
    d = ctx.current
    d.rois = [Roi("rect", [(20, 20), (40, 40)], "cell"), Roi("rect", [(60, 60), (80, 80)], "bg")]
    rows = eng.run(ctx, "fluorescence", background="roi")
    assert len(rows) == 1 and rows[0]["CTCF"] == pytest.approx(400 * 100) and rows[0]["Bkgd"] == 10
    rows = eng.run(ctx, "fluorescence", background="auto")
    assert rows[0]["CTCF"] == pytest.approx(400 * 100)


def test_wound_healing():
    w = samples.wound()
    eng, ctx = ctx_with(w)
    rows = eng.run(ctx, "wound_healing")
    truth = [100 * x / 640 for x in samples.WOUND_WIDTHS]
    assert np.allclose([r["%Area"] for r in rows], truth, atol=1.0)
    assert rows[0]["Closure %"] == 0
    assert rows[2]["Closure %"] == pytest.approx(100 * (1 - 60 / 220), abs=3)
    assert rows[0]["Mean Width"] == pytest.approx(220 * 1.3, rel=0.03)
    assert set(w.overlays) == {0, 1, 2}


# ---- scripting ---------------------------------------------------------------
def test_script_and_batch(tmp_path):
    for i in range(3):
        io.save_image(samples.nuclei(seed=10 + i), tmp_path / f"n{i}.tif")
    code = '\n'.join([format_call("gaussian", {"sigma": 1.0}),
                      format_call("count_cells", {"sigma": 0.0, "split": True}),
                      'log(image().name)'])
    assert 'run("gaussian", sigma=1.0)' in code and 'run("count_cells", sigma=0.0, split=True)' in code
    eng = Engine()
    logged = []
    out = tmp_path / "out"
    out.mkdir()
    done, failed = batch(eng, sorted(str(p) for p in tmp_path.glob("*.tif")), code, str(out), log=logged.append)
    assert done == 3 and not failed and len(logged) == 3
    assert [r["Count"] for r in eng.tables["summary"].rows] == [60, 60, 60]
    assert len(list(out.glob("*_processed.tif"))) == 3
    eng.tables["summary"].to_csv(tmp_path / "s.csv")
    assert (tmp_path / "s.csv").read_text(encoding="utf-8-sig").splitlines()[0].startswith("Label,Frame,Count")
    done, failed = batch(eng, [str(tmp_path / "n0.tif")], 'run("nope")')
    assert done == 0 and failed[0][1] == "err.unknown_op"
    eng, ctx = ctx_with(samples.blot())
    run_script(eng, ctx, 'roi("rect", [(30, 75), (530, 115)])\nrun("measure")\nrun("crop")')
    assert ctx.current.W == 500 and len(eng.tables["results"]) == 1


# ---- robustness ----------------------------------------------------------------
def _odd_images():
    rng = np.random.default_rng(5)
    yield "constant8", ImageDoc(np.full((40, 50), 7, np.uint8))
    yield "zeros16", ImageDoc(np.zeros((40, 50), np.uint16))
    yield "tiny", ImageDoc(np.array([[3]], np.uint8))
    yield "thin", ImageDoc((rng.random((1, 64)) * 255).astype(np.uint8))
    f = rng.random((30, 30)).astype(np.float32) - 0.5
    f[3, 3] = np.nan
    yield "float_nan", ImageDoc(np.nan_to_num(f))
    yield "rgb_stack", ImageDoc((rng.random((2, 3, 24, 24)) * 255).astype(np.uint8), rgb=True)
    yield "multi16", ImageDoc((rng.random((2, 3, 24, 24)) * 4000).astype(np.uint16))
    yield "binary", ImageDoc((rng.random((32, 32)) > 0.5).astype(np.uint8) * 255)


def test_no_operation_crashes_on_odd_images():
    """Every operation either works or reports a translatable OpError - never a raw exception."""
    skip = {"select", "gel", "merge_channels", "image_calculator", "images_to_stack"}
    for label, base in _odd_images():
        for name in OPS:
            if name in skip:
                continue
            for roi in (None, Roi("rect", [(0, 0), (10, 10)]), Roi("line", [(0, 0), (5, 5)])):
                doc = base.copy()
                doc.active_roi = roi
                doc.rois = [Roi("rect", [(0, 0), (5, 5)], "bg"), Roi("ellipse", [(1, 1), (9, 9)])]
                eng, ctx = ctx_with(doc)
                try:
                    eng.run(ctx, name)
                except OpError:
                    pass
                except Exception as e:  # pragma: no cover - reported with full context
                    raise AssertionError(f"{name} on {label} (roi={roi and roi.kind}): {type(e).__name__}: {e}")
                for d in ctx.docs:
                    assert np.isfinite(d.data.astype(np.float64)).all(), (name, label)
                    d.render()
        eng, ctx = ctx_with(base.copy())
        try:
            eng.run(ctx, "gel", strips=[("a", (0, 0, 20, 10))])
        except OpError:
            pass


def test_language_files_complete():
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "check_locales.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    from oris.i18n import T
    assert [c for c, _ in T.available()][:2] == ["zh-TW", "en"] and len(T.available()) >= 7
    assert T.match("zh_TW") == "zh-TW" and T.match("ja_JP") == "ja" and T.match("pt_BR") == "en"
    T.set_language("zh-TW")
    assert T.tr("menu.file") == "檔案" and T.tr("results.rows", n=3) == "3 列"
    assert T.tr("no.such.key") == "no.such.key"
    T.set_language("en")
