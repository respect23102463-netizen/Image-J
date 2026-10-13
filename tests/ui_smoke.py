"""Headless UI walk-through: exercises menus, panels, dialogs and every language, and saves screenshots.
Run: QT_QPA_PLATFORM=offscreen python tests/ui_smoke.py [output_dir]"""
import os
import sys
import tempfile
import warnings

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
warnings.filterwarnings("ignore")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()
os.makedirs(out, exist_ok=True)
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())

from oris.core.roi import Roi  # noqa: E402
from oris.core import samples  # noqa: E402
from oris.i18n import T  # noqa: E402
from oris.ui import main as M  # noqa: E402

app = QApplication([])
warnings_shown = []
M.QMessageBox.warning = staticmethod(lambda *a: warnings_shown.append(a[-1]))
win = M.MainWindow()
win.resize(1400, 880)
win.show()
app.processEvents()


def shot(name):
    app.processEvents()
    win.grab().save(os.path.join(out, name + ".png"))


def drag(canvas, a, b):
    """Simulate a mouse drag between two image coordinates."""
    vp = canvas.viewport()
    pa, pb = canvas.mapFromScene(QPointF(*a)), canvas.mapFromScene(QPointF(*b))
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, pa)
    for t in (0.3, 0.6, 1.0):
        p = QPoint(int(pa.x() + (pb.x() - pa.x()) * t), int(pa.y() + (pb.y() - pa.y()) * t))
        app.sendEvent(vp, QMouseEvent(QMouseEvent.MouseMove, QPointF(p), QPointF(vp.mapToGlobal(p)),
                                      Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, pb)
    app.processEvents()


T.set_language("en")
win.retranslate_all()
shot("00_welcome")

# ---- Western blot ---------------------------------------------------------
win.open_sample("blot")
app.processEvents()
c = win.view().canvas
drag(c, (30, 75), (530, 115))
roi = win.doc().active_roi
assert roi is not None and roi.kind == "rect", roi
assert abs(roi.bounds()[0] - 30) <= 2 and abs(roi.bounds()[2] - 530) <= 2, roi.bounds()
win.gel_panel.name.setText("Target")
win.gel_panel.add_strip()
drag(c, (30, 185), (530, 225))
win.gel_panel.name.setText("Actin")
win.gel_panel.add_strip()
win.gel_panel.lanes.setValue(6)
i = win.gel_panel.control.findData("Actin")
win.gel_panel.control.setCurrentIndex(i)
win.gel_panel.quantify()
rows = [r for r in win.engine.tables["gel"].rows if r["Strip"] == "Target"]
fold = [round(r["Fold change"], 2) for r in rows]
assert len(fold) == 6 and all(abs(a - b) < 0.03 for a, b in zip(fold, samples.BLOT_TARGET)), fold
win.gel_panel.list.setCurrentRow(0)
shot("01_western_blot")

# move, resize, measure, undo/redo
win.set_roi(Roi("rect", [(100, 50), (200, 150)]))
drag(c, (150, 100), (170, 120))
assert win.doc().active_roi.bounds()[0] == 120
drag(c, (220, 170), (240, 180))                      # drag the lower-right handle
assert win.doc().active_roi.bounds()[2:] == (240, 180), win.doc().active_roi.bounds()
win.run_op("measure")
assert len(win.engine.tables["results"]) == 1
win.run_op("gaussian", sigma=3.0)
assert win.doc().modified and win.doc().undo_stack
win.undo()
win.redo()
win.undo()
win.roi_panel.add()
assert len(win.doc().rois) == 3
win.set_tool("line")
drag(c, (50, 95), (500, 95))
assert win.doc().active_roi.kind == "line"
win.show_profile()
win.show_histogram()
win.show_info()
app.processEvents()

# ---- nuclei: threshold, particles, cell count -------------------------------
win.open_sample("nuclei")
app.processEvents()
win.show_threshold()
app.processEvents()
assert win.doc().threshold is not None
r = win.run_op("analyze_particles", min_size=5.0)
assert r["count"] >= 45, r
win.thr_dlg.close()
win.run_op("clear_threshold")
win.cell_panel.count()
assert win.cell_panel.result.text() == str(samples.NUCLEI_COUNT), win.cell_panel.result.text()
shot("02_cell_count")
win.set_tool("point")
c = win.view().canvas
for p in ((100, 100), (200, 150), (300, 300)):
    QTest.mouseClick(c.viewport(), Qt.LeftButton, Qt.NoModifier, c.mapFromScene(QPointF(*p)))
assert len(win.doc().active_roi.pts) == 3
win.cell_panel.to_results()
win.set_tool("wand")
QTest.mouseClick(c.viewport(), Qt.LeftButton, Qt.NoModifier, c.mapFromScene(QPointF(5, 5)))
assert win.doc().active_roi.kind == "polygon"
win.set_tool("polygon")
for p in ((50, 50), (150, 60), (120, 160)):
    QTest.mouseClick(c.viewport(), Qt.LeftButton, Qt.NoModifier, c.mapFromScene(QPointF(*p)))
QTest.mouseClick(c.viewport(), Qt.RightButton, Qt.NoModifier, c.mapFromScene(QPointF(120, 160)))
assert win.doc().active_roi.kind == "polygon" and len(win.doc().active_roi.pts) == 3
win.set_tool("freehand")
drag(c, (300, 300), (380, 360))
win.set_tool("ellipse")
drag(c, (200, 200), (300, 280))
assert win.doc().active_roi.kind == "ellipse"
win.run_op("crop")
assert (win.doc().W, win.doc().H) == (100, 80)
win.undo()
win.set_roi(None)

# ---- fluorescence -----------------------------------------------------------
win.open_sample("fluorescence")
app.processEvents()
win.fluor_panel.analyze()
assert len(win.engine.tables["coloc"]) == 1
win.select_all()
win.fluor_panel.measure()
assert len(win.engine.tables["fluor"]) == 2
win.show_bc()
win.bc_dlg.hi.setValue(400)
app.processEvents()
shot("03_fluorescence")
win.bc_dlg.close()
win.run_op("split_channels")
assert win.tabs.count() == 5, win.tabs.count()
win.run_op("scale_bar", length=20.0)
win.view().doc.composite = False

# ---- an ordinary RGB photo-style image (JPEG) --------------------------------
tmp_rgb = tempfile.mkdtemp()
flat = os.path.join(tmp_rgb, "merged.jpg")
for i, v in enumerate(win.views()):
    if v.doc.name == "sample-fluorescence":
        win.tabs.setCurrentIndex(i)
win.set_roi(None)
from oris.core import io as _io  # noqa: E402
_io.save_image(win.doc(), flat)
win.open_paths([flat])
d = win.doc()
assert d.rgb and d.C == 3 and d.type_label() == "RGB", (d.rgb, d.C)
win.show_histogram()
win.fluor_panel.analyze()
assert win.engine.tables["coloc"].rows[-1]["Ch1"] == "R"
win.show_bc()
win.bc_dlg.hi.setValue(500)
win.run_op("apply_contrast")
win.bc_dlg.close()
win.show_threshold()
assert d.threshold is not None
win.thr_dlg.lo.setValue(300)
win.thr_dlg.close()
win.run_op("clear_threshold")
assert win.run_op("count_cells")["count"] > 40
win.run_op("gaussian", sigma=1.0)
win.run_op("to_8bit")
assert not d.rgb and d.C == 1
win.undo()
assert d.rgb
d.modified = False
win.close_tab(win.tabs.currentIndex())

# ---- wound healing ----------------------------------------------------------
win.open_sample("wound")
app.processEvents()
win.wound_panel.measure()
assert len(win.engine.tables["wound"]) == 3
win.step_frame(1)
shot("04_wound")

# every parameterless menu operation that applies to a plain 8-bit image
win.tabs.setCurrentIndex(0)
before = win.tabs.count()
for name in ("smooth", "sharpen", "find_edges", "equalize", "invert", "log", "sqrt", "to_16bit", "to_32bit",
             "to_8bit", "to_rgb", "to_8bit", "flip_horizontal", "flip_vertical", "rotate_right", "rotate_left",
             "make_binary", "fill_holes", "outline", "skeletonize", "watershed", "distance_map", "duplicate"):
    assert win.run_op(name) is not None, (name, warnings_shown[-1:])
assert win.tabs.count() == before + 1

# parameter dialog with live preview
dlg = M.ParamDialog(win, "t", [p for p in M.OPS["gaussian"].params], {}, lambda v: win.preview_op("gaussian", v))
dlg.chk.setChecked(True)
dlg._preview()
assert win.view().canvas.preview is not None
win.preview_op("gaussian", None)
assert win.view().canvas.preview is None
for name in ("merge_channels", "image_calculator", "analyze_particles", "scale_bar", "set_scale", "rotate"):
    M.ParamDialog(win, name, [p for p in M.OPS[name].params if p["type"] != "raw"], {}).values()

# modal parameter dialogs opened from the menus (accepted automatically)
from PySide6.QtCore import QTimer  # noqa: E402


def accept_next():
    def go():
        w = app.activeModalWidget()
        if w is not None:
            w.accept()
        else:
            QTimer.singleShot(50, go)
    QTimer.singleShot(50, go)


win.tabs.setCurrentIndex(1)
win.run_op("clear_threshold")
d = win.doc()
n_undo = len(d.undo_stack)
for name in ("gaussian", "median", "subtract_background", "enhance_contrast", "rotate", "scale"):
    accept_next()
    win.ask_op(name)
    assert len(d.undo_stack) == min(n_undo + 1, d.MAX_UNDO), name
    win.undo()
win.set_tool("line")
drag(win.view().canvas, (100, 100), (300, 100))
accept_next()
win.ask_op("set_scale")
assert abs(d.pixel_size - 1 / 200) < 1e-4 and d.unit == "\u00b5m", (d.pixel_size, d.unit)
accept_next()
win.ask_op("scale_bar")
assert d.scale_bar is not None
win.run_op("set_threshold")
accept_next()
win.ask_op("analyze_particles")
assert len(win.engine.tables["particles"]) > 54
win.run_op("clear_threshold")
accept_next()
win.ask_op("z_project")
accept_next()
win.ask_op("image_calculator")
accept_next()
win.ask_op("rename")
win.run_op("set_lut", name="fire")
assert win.doc().luts[0] == "fire"
win.run_op("set_lut", name="grays")
win.set_roi(None)

# ROI manager
win.tabs.setCurrentIndex(1)
rp = win.roi_panel
n0 = len(win.doc().rois)
win.set_roi(Roi("rect", [(10, 10), (60, 50)]))
rp.add()
win.set_roi(Roi("ellipse", [(100, 100), (160, 150)]))
rp.add()
assert rp.list.count() == n0 + 2
rp.list.setCurrentRow(n0)
assert win.doc().active_roi.kind == "rect"
win.set_roi(Roi("rect", [(20, 20), (70, 60)]))
rp.update_roi()
assert win.doc().rois[n0].bounds() == (20, 20, 70, 60)
n_res = len(win.engine.tables["results"])
win.run_op("measure_all")
assert len(win.engine.tables["results"]) == n_res + n0 + 2
rp.list.setCurrentRow(n0 + 1)
rp.delete()
assert len(win.doc().rois) == n0 + 1
rp.clear()
assert not win.doc().rois

# batch dialog on a folder of images
from oris.ui.dialogs import BatchDialog  # noqa: E402
bdir, bout = tempfile.mkdtemp(), tempfile.mkdtemp()
for i in range(2):
    _io.save_image(samples.nuclei(seed=20 + i), os.path.join(bdir, f"img{i}.tif"))
bd = BatchDialog(win)
bd.src.setText(bdir)
bd.dst.setText(bout)
bd.editor.setPlainText('run("count_cells")')
n_sum = len(win.engine.tables["summary"])
bd.run()
assert len(win.engine.tables["summary"]) == n_sum + 2 and len(os.listdir(bout)) == 2, bd.out.toPlainText()
assert win.engine.tables["summary"].rows[-1]["Count"] == samples.NUCLEI_COUNT

# scripting, batch dialog, export
win.show_script()
sd = win._dialogs[-1]
sd.editor.setPlainText('run("gaussian", sigma=1.0)\nrun("measure")\nlog("ok")')
sd.run()
assert "ok" in sd.out.toPlainText(), sd.out.toPlainText()
sd.editor.setPlainText('run("nope")')
sd.run()
assert "nope" in sd.out.toPlainText()
win.show_batch()
assert "run(" in win.recorded_script()
from oris.ui.canvas import flatten  # noqa: E402
win.tabs.setCurrentIndex(1)
img = flatten(win.doc())
assert img.width() == win.doc().W
img.save(os.path.join(out, "flatten.png"))
tmp = tempfile.mkdtemp()
assert win._write(win.doc(), os.path.join(tmp, "x.tif"))
win.open_paths([os.path.join(tmp, "x.tif")])
assert win.view().doc.W == 512
win.results_panel.which.setCurrentIndex(0)
win.engine.tables["results"].to_csv(os.path.join(tmp, "r.csv"))

# ---- every language ----------------------------------------------------------
win.open_sample("blot")
win.set_tool("rect")
app.processEvents()
c = win.view().canvas
for nm, (y0, y1) in (("p-AKT", (75, 115)), ("\u03b2-actin", (185, 225))):
    drag(c, (30, y0), (530, y1))
    win.gel_panel.name.setText(nm)
    win.gel_panel.add_strip()
win.gel_panel.lanes.setValue(6)
win.gel_panel.control.setCurrentIndex(win.gel_panel.control.findData("\u03b2-actin"))
win.gel_panel.quantify()
win.gel_panel.list.setCurrentRow(0)
win.results_panel.view.scrollToTop()
for code, name in T.available():
    win.set_language(code)
    app.processEvents()
    assert T.lang == code
    win.results_panel.view.scrollToTop()
    shot("lang_" + code)
win.set_language("zh-TW")
win.set_theme("light")
shot("05_light_theme")
win.set_theme("dark")
for v in win.views():
    v.doc.modified = False
unexpected = [w for w in warnings_shown if "nope" not in str(w)]
assert not unexpected, unexpected
print("tabs:", win.tabs.count(), "tables:", {k: len(t) for k, t in win.engine.tables.items()})
print("screenshots in", out)
win.close()
