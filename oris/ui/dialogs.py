"""Dialogs: parameters, brightness/contrast, threshold, plots, script editor, batch, help."""
from __future__ import annotations

import csv
import glob
import os

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QSlider,
                               QSplitter, QTextBrowser, QVBoxLayout)

from ..core import filters as flt, measure as ms
from ..core.engine import batch
from ..core.io import READ_EXT
from ..i18n import T, tr
from .plot import PlotWidget
from .theme import C
from .util import dspin, set_combo, spin


def mono_font():
    f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    f.setPointSizeF(max(9.0, f.pointSizeF()))
    return f


class ParamDialog(QDialog):
    """Build a form from an operation's parameter specs."""

    def __init__(self, win, title, specs, values=None, preview=None):
        super().__init__(win)
        self.setWindowTitle(title)
        self.setMinimumWidth(340)
        self.win, self.preview, self.widgets = win, preview, {}
        values = values or {}
        lay = QVBoxLayout(self)
        form = QFormLayout()
        lay.addLayout(form)
        n_image = 0
        for s in specs:
            name, typ = s["name"], s["type"]
            if typ == "raw":
                continue
            v = values.get(name, s["default"])
            if typ == "float":
                rng = abs(s["hi"] - s["lo"])
                w = dspin(v, s["lo"], s["hi"], self._changed, decimals=3 if rng <= 10 else 2)
                if name == "max_size":
                    w.setSpecialValueText(tr("cells.no_limit"))      # 0 means "no upper limit"
            elif typ == "int":
                w = spin(v, s["lo"], s["hi"], self._changed)
            elif typ == "bool":
                w = QCheckBox()
                w.setChecked(bool(v))
                w.toggled.connect(self._changed)
            elif typ == "choice":
                w = QComboBox()
                for c in s["choices"]:
                    w.addItem(T.opt("choice." + c, c), c)
                set_combo(w, v)
                w.currentIndexChanged.connect(self._changed)
            elif typ in ("image", "image_opt"):
                w = QComboBox()
                if typ == "image_opt":
                    w.addItem(tr("choice.none"), "none")
                names = [d.name for d in win.ctx.docs]
                for nm in names:
                    w.addItem(nm, nm)
                if v in names:
                    w.setCurrentIndex(w.findData(v))
                elif typ == "image" and names:
                    w.setCurrentIndex(min(n_image, len(names) - 1))
                n_image += typ == "image"
            elif typ == "channel":
                w = QComboBox()
                doc = win.doc()
                for i, nm in enumerate(doc.channel_names() if doc else []):
                    w.addItem(nm, i)
                w.setCurrentIndex(min(int(v), max(w.count() - 1, 0)))
            else:
                w = QLineEdit(str(v))
            self.widgets[name] = (typ, w)
            form.addRow(T.opt("param." + name, name), w)
        self.chk = None
        if preview:
            self.chk = QCheckBox(tr("dlg.preview"))
            self.chk.toggled.connect(self._changed)
            lay.addWidget(self.chk)
            self.timer = QTimer(self)
            self.timer.setSingleShot(True)
            self.timer.setInterval(220)
            self.timer.timeout.connect(self._preview)
        bb = QDialogButtonBox()
        ok = bb.addButton(tr("dlg.ok"), QDialogButtonBox.AcceptRole)
        ok.setProperty("primary", True)
        bb.addButton(tr("dlg.cancel"), QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        out = {}
        for name, (typ, w) in self.widgets.items():
            if typ in ("float", "int"):
                out[name] = w.value()
            elif typ == "bool":
                out[name] = w.isChecked()
            elif typ in ("choice", "image", "image_opt", "channel"):
                out[name] = w.currentData()
            else:
                out[name] = w.text()
        return out

    def _changed(self, *_):
        if self.chk is not None:
            if self.chk.isChecked():
                self.timer.start()
            else:
                self.preview(None)

    def _preview(self):
        if self.chk is not None and self.chk.isChecked():
            self.preview(self.values())


class RangeDialog(QDialog):
    """Histogram with two sliders; base for brightness/contrast and threshold."""
    STEPS = 1000

    def __init__(self, win, title_key):
        super().__init__(win)
        self.win = win
        self.setWindowTitle(tr(title_key))
        self.setWindowFlag(Qt.Tool, True)
        self.setMinimumWidth(330)
        self._busy = False
        self.full = (0.0, 255.0)
        self.lay = QVBoxLayout(self)
        self.plot = PlotWidget(min_height=130)
        self.lay.addWidget(self.plot)
        self.value_label = QLabel()
        self.value_label.setAlignment(Qt.AlignCenter)
        self.lay.addWidget(self.value_label)
        form = QFormLayout()
        self.lo, self.hi = QSlider(Qt.Horizontal), QSlider(Qt.Horizontal)
        for s in (self.lo, self.hi):
            s.setRange(0, self.STEPS)
            s.valueChanged.connect(self._moved)
            s.sliderReleased.connect(self._released)
        form.addRow(tr(self.LABELS[0]), self.lo)
        form.addRow(tr(self.LABELS[1]), self.hi)
        self.lay.addLayout(form)

    def _to_value(self, pos):
        a, b = self.full
        return a + (b - a) * pos / self.STEPS

    def _to_pos(self, v):
        a, b = self.full
        return int(round((min(max(v, a), b) - a) / (b - a) * self.STEPS)) if b > a else 0

    def _plane(self, doc):
        return doc.gray()

    def refresh(self):
        doc = self.win.doc()
        self.setEnabled(doc is not None)
        if doc is None:
            self.plot.clear()
            return
        g = self._plane(doc)
        if g.dtype == np.uint8 or doc.rgb:
            self.full = (0.0, 255.0)
        else:
            cur = self.current(doc) or (float(g.min()), float(g.max()))
            lo, hi = min(float(g.min()), cur[0]), max(float(g.max()), cur[1])
            self.full = (lo, hi if hi > lo else lo + 1)
        self.hist, self.edges = ms.histogram(g, 256, self.full)
        cur = self.current(doc) or self.full
        self._busy = True
        self.lo.setValue(self._to_pos(cur[0]))
        self.hi.setValue(self._to_pos(cur[1]))
        self._busy = False
        self._draw(cur)

    def _draw(self, cur):
        self.plot.set_data([{"x": self.edges[:-1], "y": self.hist, "fill": True, "color": C["muted"]}],
                           spans=[(cur[0], cur[1], C["accent"])], xrange=self.full, logy=True)
        self.value_label.setText(f"{cur[0]:.6g}  –  {cur[1]:.6g}")

    def _moved(self, *_):
        if self._busy:
            return
        doc = self.win.doc()
        if doc is None:
            return
        lo, hi = self._to_value(self.lo.value()), self._to_value(self.hi.value())
        if hi < lo:
            lo, hi = hi, lo
        self.apply_live(doc, lo, hi)
        self._draw((lo, hi))
        self.win.refresh_canvas()

    def _released(self):
        doc = self.win.doc()
        if doc is not None and self.current(doc):
            self.commit(doc, *self.current(doc))


class BCDialog(RangeDialog):
    LABELS = ("bc.minimum", "bc.maximum")

    def __init__(self, win):
        super().__init__(win, "bc.title")
        row = QHBoxLayout()
        for key, op in (("bc.auto", "auto_contrast"), ("bc.reset", "reset_contrast"), ("bc.apply", "apply_contrast")):
            b = QPushButton(tr(key))
            b.clicked.connect(lambda *_, o=op: self.win.run_op(o))
            row.addWidget(b)
        self.lay.addLayout(row)
        self.refresh()

    def _plane(self, doc):
        return doc.data[doc.frame] if doc.rgb else doc.plane()

    def current(self, doc):
        return doc.ranges[0 if doc.rgb else doc.channel]

    def apply_live(self, doc, lo, hi):
        for c in (range(3) if doc.rgb else [doc.channel]):
            doc.ranges[c] = (lo, max(hi, lo + 1e-6))

    def commit(self, doc, lo, hi):
        self.win.record("set_range", {"lower": round(lo, 4), "upper": round(hi, 4)})


class ThresholdDialog(RangeDialog):
    LABELS = ("thr.lower", "thr.upper")

    def __init__(self, win):
        super().__init__(win, "thr.title")
        form = QFormLayout()
        self.method = QComboBox()
        for m in flt.THRESHOLD_METHODS + ["manual"]:
            self.method.addItem(T.opt("choice." + m, m), m)
        self.bg = QComboBox()
        for m in ("auto", "dark", "light"):
            self.bg.addItem(tr("choice." + m), m)
        self.method.currentIndexChanged.connect(self._auto)
        self.bg.currentIndexChanged.connect(self._auto)
        form.addRow(tr("param.method"), self.method)
        form.addRow(tr("param.background"), self.bg)
        self.lay.addLayout(form)
        row = QHBoxLayout()
        apply_btn = QPushButton(tr("thr.apply"))
        apply_btn.setProperty("primary", True)
        apply_btn.clicked.connect(lambda *_: self.win.run_op("make_binary"))
        reset = QPushButton(tr("thr.reset"))
        reset.clicked.connect(lambda *_: self.win.run_op("clear_threshold"))
        row.addWidget(reset)
        row.addWidget(apply_btn)
        self.lay.addLayout(row)
        hint = QLabel(tr("thr.hint"))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        self.lay.addWidget(hint)
        self.ensure()

    def ensure(self):
        """Give the current image an automatic threshold if it has none yet."""
        doc = self.win.doc()
        if doc is not None and doc.threshold is None and not flt.is_binary(doc.gray()):
            if self.method.currentData() == "manual":
                self._busy = True
                set_combo(self.method, "otsu")
                self._busy = False
            self._auto()
        self.refresh()

    def current(self, doc):
        return doc.threshold

    def apply_live(self, doc, lo, hi):
        doc.threshold = (lo, hi)
        self._busy = True
        set_combo(self.method, "manual")
        self._busy = False

    def commit(self, doc, lo, hi):
        self.win.record("set_threshold", {"method": "manual", "lower": round(lo, 4), "upper": round(hi, 4)})

    def _auto(self, *_):
        if self._busy or self.method.currentData() == "manual" or self.win.doc() is None:
            return
        self.win.run_op("set_threshold", method=self.method.currentData(), background=self.bg.currentData())


class PlotDialog(QDialog):
    """A plot with a statistics line and CSV export."""

    def __init__(self, win, title):
        super().__init__(win)
        self.setWindowTitle(title)
        self.resize(560, 380)
        self.columns = {}
        lay = QVBoxLayout(self)
        self.plot = PlotWidget()
        lay.addWidget(self.plot, 1)
        self.info = QLabel()
        self.info.setProperty("role", "hint")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.info)
        row = QHBoxLayout()
        self.log = QCheckBox(tr("plot.log"))
        row.addWidget(self.log)
        row.addStretch(1)
        save = QPushButton(tr("plot.save_csv"))
        save.clicked.connect(self._save)
        close = QPushButton(tr("dlg.close"))
        close.clicked.connect(self.close)
        row.addWidget(save)
        row.addWidget(close)
        lay.addLayout(row)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("plot.save_csv"), "plot.csv", "CSV (*.csv)")
        if path:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(self.columns)
                w.writerows(zip(*self.columns.values()))


class ScriptDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle(tr("script.title"))
        self.resize(680, 560)
        lay = QVBoxLayout(self)
        hint = QLabel(tr("script.hint"))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        split = QSplitter(Qt.Vertical)
        self.editor = QPlainTextEdit()
        self.editor.setFont(mono_font())
        self.editor.setPlainText(win.recorded_script() or '# run("gaussian", sigma=2.0)\n# run("measure")\n')
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(mono_font())
        split.addWidget(self.editor)
        split.addWidget(self.out)
        split.setSizes([380, 140])
        lay.addWidget(split, 1)
        row = QHBoxLayout()
        for key, slot in (("script.open", self._open), ("script.save", self._save),
                          ("script.insert", lambda: self.editor.setPlainText(win.recorded_script()))):
            b = QPushButton(tr(key))
            b.clicked.connect(lambda *_, s=slot: s())
            row.addWidget(b)
        row.addStretch(1)
        run = QPushButton(tr("script.run"))
        run.setProperty("primary", True)
        run.clicked.connect(lambda *_: self.run())
        row.addWidget(run)
        lay.addLayout(row)

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("script.open"), "", "Python (*.py);;*")
        if path:
            with open(path, encoding="utf-8") as fh:
                self.editor.setPlainText(fh.read())

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("script.save"), "macro.py", "Python (*.py)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.editor.toPlainText())

    def run(self):
        self.out.clear()
        ok, msg = self.win.run_script(self.editor.toPlainText(),
                                      lambda *a: self.out.appendPlainText(" ".join(str(x) for x in a)))
        self.out.appendPlainText(tr("script.done") if ok else msg)


class BatchDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle(tr("batch.title"))
        self.resize(680, 600)
        lay = QVBoxLayout(self)
        hint = QLabel(tr("batch.hint"))
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        form = QFormLayout()
        self.src, self.dst = QLineEdit(), QLineEdit()
        for edit, key in ((self.src, "batch.input"), (self.dst, "batch.output")):
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            b = QPushButton(tr("batch.browse"))
            b.clicked.connect(lambda *_, e=edit: self._browse(e))
            row.addWidget(b)
            form.addRow(tr(key), row)
        self.dst.setPlaceholderText(tr("batch.output_hint"))
        lay.addLayout(form)
        self.editor = QPlainTextEdit()
        self.editor.setFont(mono_font())
        self.editor.setPlainText(win.recorded_script())
        lay.addWidget(self.editor, 2)
        self.bar = QProgressBar()
        lay.addWidget(self.bar)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(mono_font())
        lay.addWidget(self.out, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.run_btn = QPushButton(tr("batch.run"))
        self.run_btn.setProperty("primary", True)
        self.run_btn.clicked.connect(lambda *_: self.run())
        row.addWidget(self.run_btn)
        lay.addLayout(row)

    def _browse(self, edit):
        d = QFileDialog.getExistingDirectory(self, tr("batch.browse"), edit.text())
        if d:
            edit.setText(d)

    def files(self):
        src = self.src.text().strip()
        return sorted(f for f in glob.glob(os.path.join(src, "*")) if f.lower().endswith(READ_EXT)) if src else []

    def run(self):
        files = self.files()
        if not files:
            self.out.appendPlainText(tr("batch.no_files"))
            return
        dst = self.dst.text().strip() or None
        if dst:
            os.makedirs(dst, exist_ok=True)
        self.bar.setRange(0, len(files))
        self.run_btn.setEnabled(False)

        def progress(i, n, path):
            self.bar.setValue(i)
            self.out.appendPlainText(os.path.basename(path))
            QApplication.processEvents()

        try:
            done, failed = batch(self.win.engine, files, self.editor.toPlainText(), dst, progress,
                                 lambda *a: self.out.appendPlainText("  " + " ".join(str(x) for x in a)))
        finally:
            self.run_btn.setEnabled(True)
        self.bar.setValue(len(files))
        for path, msg in failed:
            self.out.appendPlainText(f"! {os.path.basename(path)}: {tr(msg) if msg.startswith('err.') else msg}")
        self.out.appendPlainText(tr("batch.done", done=done, total=len(files)))
        self.win.refresh_all()


class HelpDialog(QDialog):
    def __init__(self, win, title, html):
        super().__init__(win)
        self.setWindowTitle(title)
        self.resize(620, 560)
        lay = QVBoxLayout(self)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setHtml(html)
        lay.addWidget(view)
        b = QPushButton(tr("dlg.close"))
        b.clicked.connect(self.close)
        lay.addWidget(b, 0, Qt.AlignRight)
