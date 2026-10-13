"""Dock panels: ROI manager, Western blot, cell counting, fluorescence, wound healing, results, recorder."""
from __future__ import annotations

import json

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QScrollArea,
                               QTableView, QToolButton, QVBoxLayout, QWidget, QAbstractSpinBox)

from ..core import analysis as an
from ..core.filters import THRESHOLD_METHODS
from ..core.roi import Roi
from ..i18n import tr
from .dialogs import mono_font
from .plot import PlotWidget
from .theme import C, CATEGORY_COLORS
from .util import TableModel, Tr, dspin, set_combo, spin


class Panel(QWidget, Tr):
    """Base: scrollable column of widgets with live translation."""

    def __init__(self, win):
        super().__init__()
        self._tr_setup()
        self.win = win
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        self.col = QVBoxLayout(body)
        self.col.setContentsMargins(10, 10, 10, 10)
        self.col.setSpacing(8)
        scroll.setWidget(body)
        outer.addWidget(scroll)

    def group(self, key):
        g = QGroupBox()
        self.T(g, key, "setTitle")
        self.col.addWidget(g)
        return g

    def advanced(self):
        """A collapsed "Advanced settings" section; returns the form layout inside it."""
        btn = QToolButton()
        btn.setCheckable(True)
        btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn.setArrowType(Qt.RightArrow)
        btn.setProperty("role", "disclosure")
        self.T(btn, "panel.advanced")
        box = QWidget()
        box.setVisible(False)
        form = QFormLayout(box)
        form.setContentsMargins(4, 0, 0, 4)

        def toggle(on):
            box.setVisible(on)
            btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        btn.toggled.connect(toggle)
        self.col.addWidget(btn)
        self.col.addWidget(box)
        return form

    def form_row(self, form, key, widget):
        form.addRow(self.label(key), widget)
        return widget

    def refresh(self):
        pass

    def fit_width(self):
        """Let the panel shrink to the dock width in every language: long labels wrap above their field,
        and input fields are allowed to become narrower than their longest entry."""
        for form in self.findChildren(QFormLayout):
            form.setRowWrapPolicy(QFormLayout.WrapLongRows)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for c in self.findChildren(QComboBox):
            c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(4)
            c.setMinimumWidth(80)
        for sb in self.findChildren(QAbstractSpinBox):
            sb.setMinimumWidth(80)
        for lab in self.findChildren(QLabel):
            if lab.property("role") == "hint":
                lab.setWordWrap(True)
        for g in self.findChildren(QGroupBox):
            g.setMinimumWidth(0)


# ---------------------------------------------------------------------------
class RoiPanel(Panel):
    def __init__(self, win):
        super().__init__(win)
        self.col.addWidget(self.label("roi.hint", "hint", True))
        self.list = QListWidget()
        self.list.setMinimumHeight(150)
        self.list.currentRowChanged.connect(self._select)
        self.col.addWidget(self.list, 1)
        grid = QGridLayout()
        buttons = [("roi.add", self.add, True), ("roi.update", self.update_roi, False),
                   ("roi.rename", self.rename, False), ("roi.delete", self.delete, False),
                   ("roi.measure", lambda: win.run_op("measure"), False),
                   ("roi.measure_all", lambda: win.run_op("measure_all"), False),
                   ("roi.save", self.save, False), ("roi.load", self.load, False)]
        for i, (key, slot, primary) in enumerate(buttons):
            grid.addWidget(self.button(key, slot, primary), i // 2, i % 2)
        self.col.addLayout(grid)
        self.col.addWidget(self.button("roi.clear", self.clear))
        self.show_all = self.T(QCheckBox(), "roi.show_all")
        self.show_all.setChecked(True)
        self.show_all.toggled.connect(self._toggle_show)
        self.col.addWidget(self.show_all)
        self.info = QLabel()
        self.info.setProperty("role", "hint")
        self.info.setWordWrap(True)
        self.col.addWidget(self.info)

    def refresh(self):
        doc = self.win.doc()
        self.list.blockSignals(True)
        self.list.clear()
        if doc is not None:
            for i, r in enumerate(doc.rois):
                self.list.addItem(f"{i + 1}.  {r.name or tr('kind.' + r.kind)}")
        self.list.blockSignals(False)
        self.update_info()

    def update_info(self):
        doc = self.win.doc()
        roi = doc.active_roi if doc else None
        if roi is None:
            self.info.setText(tr("roi.none"))
            return
        px, u = doc.pixel_size, doc.unit
        if roi.kind == "point":
            text = tr("roi.info_points", n=len(roi.pts))
        elif roi.kind == "line":
            text = tr("roi.info_line", length=f"{roi.length() * px:.2f} {u}", angle=f"{roi.angle():.1f}")
        else:
            x0, y0, x1, y1 = roi.bounds()
            text = tr("roi.info_area", kind=tr("kind." + roi.kind), w=f"{(x1 - x0) * px:.2f}",
                      h=f"{(y1 - y0) * px:.2f}", unit=u, x=f"{x0:.0f}", y=f"{y0:.0f}")
        self.info.setText(text)

    def _select(self, row):
        doc = self.win.doc()
        if doc is not None and 0 <= row < len(doc.rois):
            doc.active_roi = doc.rois[row].copy()
            self.win.refresh_canvas()
            self.update_info()

    def _toggle_show(self, on):
        for view in self.win.views():
            view.canvas.show_all = on
            view.canvas.viewport().update()

    def add(self):
        doc = self.win.doc()
        if doc is None or doc.active_roi is None:
            self.win.warn(tr("err.no_roi"))
            return
        doc.rois.append(doc.active_roi.copy())
        self.win.refresh_all()

    def update_roi(self):
        doc, row = self.win.doc(), self.list.currentRow()
        if doc is not None and doc.active_roi is not None and 0 <= row < len(doc.rois):
            new = doc.active_roi.copy()
            new.name = doc.rois[row].name
            doc.rois[row] = new
            self.win.refresh_all()

    def rename(self):
        doc, row = self.win.doc(), self.list.currentRow()
        if doc is None or not 0 <= row < len(doc.rois):
            return
        name, ok = QInputDialog.getText(self, tr("roi.rename"), tr("param.name"), text=doc.rois[row].name)
        if ok:
            doc.rois[row].name = name.strip()
            self.win.refresh_all()

    def delete(self):
        doc, row = self.win.doc(), self.list.currentRow()
        if doc is not None and 0 <= row < len(doc.rois):
            del doc.rois[row]
            self.win.refresh_all()

    def clear(self):
        doc = self.win.doc()
        if doc is not None:
            doc.rois = []
            doc.active_roi = None
            self.win.refresh_all()

    def save(self):
        doc = self.win.doc()
        if doc is None or not doc.rois:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("roi.save"), "rois.json", "JSON (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump([r.to_dict() for r in doc.rois], fh)

    def load(self):
        doc = self.win.doc()
        if doc is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("roi.load"), "", "JSON (*.json)")
        if path:
            try:
                with open(path, encoding="utf-8") as fh:
                    doc.rois += [Roi.from_dict(d) for d in json.load(fh)]
            except (OSError, ValueError, KeyError) as e:
                self.win.warn(str(e))
            self.win.refresh_all()


# ---------------------------------------------------------------------------
class GelPanel(Panel):
    """Western blot / gel band quantification."""

    def __init__(self, win):
        super().__init__(win)
        self.col.addWidget(self.label("gel.hint", "hint", True))
        g = self.group("gel.strips")
        v = QVBoxLayout(g)
        row = QHBoxLayout()
        self.name = QLineEdit()
        self.T(self.name, "gel.name_placeholder", "setPlaceholderText")
        row.addWidget(self.name, 1)
        row.addWidget(self.button("gel.add", self.add_strip, True))
        v.addLayout(row)
        self.list = QListWidget()
        self.list.setMaximumHeight(96)
        self.list.currentRowChanged.connect(lambda *_: self.update_plot())
        v.addWidget(self.list)
        row = QHBoxLayout()
        row.addWidget(self.button("gel.remove", self.remove_strip))
        row.addWidget(self.button("gel.clear", self.clear_strips))
        v.addLayout(row)

        form = QFormLayout()
        self.col.addLayout(form)
        self.lanes = self.form_row(form, "param.lanes", spin(0, 0, 200, self.update_plot))
        self.T(self.lanes, "gel.auto", "setSpecialValueText")
        self.control = QComboBox()
        self.form_row(form, "param.control", self.control)

        self.plot = PlotWidget(min_height=170)
        self.plot.setMaximumHeight(240)
        self.col.addWidget(self.plot)
        self.band_info = QLabel()
        self.band_info.setProperty("role", "hint")
        self.band_info.setWordWrap(True)
        self.col.addWidget(self.band_info)
        self.col.addWidget(self.button("gel.quantify", self.quantify, True))

        form = self.advanced()
        self.axis = self.form_row(form, "param.axis", self.combo(["row", "lane"], slot=self.update_plot))
        self.reference = self.form_row(form, "param.reference", spin(1, 1, 200))
        self.mode = self.form_row(form, "param.mode", self.combo(["auto", "even"], slot=self.update_plot))
        self.polarity = self.form_row(form, "param.polarity", self.combo(["auto", "dark", "light"],
                                                                        "choice.bands_", self.update_plot))
        self.bg = self.form_row(form, "param.bg_radius", spin(0, 0, 5000, self.update_plot))
        self.T(self.bg, "gel.auto", "setSpecialValueText")
        self.prom = self.form_row(form, "param.prominence", dspin(5.0, 0.1, 100.0, self.update_plot, 0.5, 1))
        self.col.addStretch(1)

    def strips(self):
        doc = self.win.doc()
        if doc is None:
            return []
        if not hasattr(doc, "gel_strips"):
            doc.gel_strips = []
        return doc.gel_strips

    def params(self):
        return dict(axis=self.axis.currentData(), lanes=self.lanes.value(), mode=self.mode.currentData(),
                    polarity=self.polarity.currentData(), bg_radius=self.bg.value(), prominence=self.prom.value())

    def refresh(self):
        strips = self.strips()
        cur = max(self.list.currentRow(), 0)
        self.list.blockSignals(True)
        self.list.clear()
        for name, rect in strips:
            self.list.addItem(f"{name}   [{rect[2] - rect[0]:.0f} × {rect[3] - rect[1]:.0f}]")
        if strips:
            self.list.setCurrentRow(min(cur, len(strips) - 1))
        self.list.blockSignals(False)
        ctrl = self.control.currentData()
        self.control.blockSignals(True)
        self.control.clear()
        self.control.addItem(tr("choice.none"), "")
        for name, _ in strips:
            self.control.addItem(name, name)
        set_combo(self.control, ctrl)
        self.control.blockSignals(False)
        self.update_plot()

    def retranslate(self):
        super().retranslate()
        self.refresh()

    def add_strip(self):
        doc = self.win.doc()
        roi = doc.active_roi if doc else None
        if roi is None or roi.kind != "rect":
            self.win.warn(tr("err.need_rect"))
            return
        strips = self.strips()
        name = self.name.text().strip() or tr("gel.default_name", n=len(strips) + 1)
        if any(n == name for n, _ in strips):
            name = f"{name} {len(strips) + 1}"
        rect = tuple(int(round(v)) for v in roi.bounds())
        strips.append((name, rect))
        doc.rois.append(Roi("rect", [rect[:2], rect[2:]], name))
        self.name.clear()
        self.win.refresh_all()
        self.list.setCurrentRow(len(strips) - 1)

    def remove_strip(self):
        doc, strips, row = self.win.doc(), self.strips(), self.list.currentRow()
        if 0 <= row < len(strips):
            name = strips.pop(row)[0]
            doc.rois = [r for r in doc.rois if not (r.kind == "rect" and r.name == name)]
            self.win.refresh_all()

    def clear_strips(self):
        doc, strips = self.win.doc(), self.strips()
        if doc is not None:
            names = {n for n, _ in strips}
            doc.rois = [r for r in doc.rois if not (r.kind == "rect" and r.name in names)]
            strips.clear()
            self.win.refresh_all()

    def update_plot(self):
        doc, strips, row = self.win.doc(), self.strips(), self.list.currentRow()
        if doc is None or not 0 <= row < len(strips):
            self.plot.set_data(message=tr("gel.plot_empty"))
            self.band_info.setText("")
            return
        try:
            r = an.analyze_strip(doc.gray(), strips[row][1], vmax=doc.dtype_max, **self.params())
        except ValueError:
            self.plot.set_data(message=tr("err.roi_too_small"))
            return
        x = np.arange(r["profile"].size) + r["offset"]
        spans = [(b["start"] + r["offset"], b["end"] + r["offset"], C["accent"]) for b in r["bands"]]
        self.plot.set_data([{"x": x, "y": r["profile"], "color": C["text"]},
                            {"x": x, "y": r["baseline"], "color": "#ff9f43", "dash": True}],
                           spans=spans, xlabel=tr("gel.position"), ylabel=tr("gel.density"),
                           yrange=(float(min(r["profile"].min(), r["baseline"].min())), float(r["profile"].max()) * 1.05))
        self.band_info.setText(tr("gel.bands_found", n=len(r["bands"])) + "   " +
                               "  ".join(f"{b['percent']:.1f}%" for b in r["bands"][:12]))

    def quantify(self):
        strips = self.strips()
        if not strips:
            self.win.warn(tr("err.no_strips"))
            return
        self.win.run_op("gel", strips=list(strips), control=self.control.currentData() or "",
                        reference=self.reference.value(), **self.params())


# ---------------------------------------------------------------------------
class CellPanel(Panel):
    def __init__(self, win):
        super().__init__(win)
        self.col.addWidget(self.label("cells.hint", "hint", True))
        self.col.addWidget(self.button("cells.count", self.count, True))
        self.result = QLabel("")
        self.result.setProperty("role", "big")
        self.result.setAlignment(Qt.AlignCenter)
        self.result.setVisible(False)          # shown once there is a result
        self.col.addWidget(self.result)
        form = self.advanced()
        self.sigma = self.form_row(form, "param.sigma", dspin(1.5, 0.0, 50.0, step=0.5, decimals=1))
        self.bg_radius = self.form_row(form, "param.bg_radius", dspin(0.0, 0.0, 1000.0, step=10, decimals=0))
        self.T(self.bg_radius, "cells.off", "setSpecialValueText")
        self.method = self.form_row(form, "param.method", self.combo(THRESHOLD_METHODS))
        self.background = self.form_row(form, "param.background", self.combo(["auto", "dark", "light"]))
        self.split = self.T(QCheckBox(), "param.split")
        self.split.setChecked(True)
        form.addRow(self.split)
        self.tolerance = self.form_row(form, "param.tolerance", dspin(1.0, 0.1, 50.0, step=0.5, decimals=1))
        self.min_size = self.form_row(form, "param.min_size", dspin(0.0, 0.0, 1e9, step=10, decimals=1))
        self.max_size = self.form_row(form, "param.max_size", dspin(0.0, 0.0, 1e9, step=100, decimals=1))
        self.T(self.max_size, "cells.no_limit", "setSpecialValueText")
        self.min_circ = self.form_row(form, "param.min_circ", dspin(0.0, 0.0, 1.0, step=0.05))
        self.exclude = self.T(QCheckBox(), "param.exclude_edges")
        self.to_manager = self.T(QCheckBox(), "param.add_to_manager")
        self.all_frames = self.T(QCheckBox(), "param.all_frames")
        for w in (self.exclude, self.to_manager, self.all_frames):
            form.addRow(w)

        g = self.group("cells.manual")
        v = QVBoxLayout(g)
        v.addWidget(self.label("cells.manual_hint", "hint", True))
        form = QFormLayout()
        self.category = QComboBox()
        for i, col in enumerate(CATEGORY_COLORS):
            self.category.addItem("", i)
        self.category.currentIndexChanged.connect(self._category)
        form.addRow(self.label("cells.type"), self.category)
        v.addLayout(form)
        self.counts = QLabel()
        self.counts.setWordWrap(True)
        v.addWidget(self.counts)
        v.addWidget(self.button("cells.start", lambda: win.set_tool("point")))
        v.addWidget(self.button("cells.to_results", self.to_results))
        self.col.addStretch(1)
        self._category_names()

    def _category_names(self):
        for i in range(self.category.count()):
            self.category.setItemText(i, tr("cells.type_n", n=i + 1))

    def retranslate(self):
        super().retranslate()
        self._category_names()
        self.refresh()

    def _category(self, *_):
        for view in self.win.views():
            view.canvas.category = self.category.currentData()

    def _counts(self):
        doc = self.win.doc()
        roi = doc.active_roi if doc else None
        if roi is None or roi.kind != "point":
            return {}
        out = {}
        for c in roi.cats:
            out[c] = out.get(c, 0) + 1
        return out

    def refresh(self):
        counts = self._counts()
        total = sum(counts.values())
        parts = [f'<span style="color:{CATEGORY_COLORS[c]}">●</span> {tr("cells.type_n", n=c + 1)}: <b>{n}</b>'
                 for c, n in sorted(counts.items())]
        self.counts.setText(tr("cells.total", n=total) + ("<br>" + "<br>".join(parts) if parts else ""))

    def to_results(self):
        doc, counts = self.win.doc(), self._counts()
        if doc is None or not counts:
            return
        t = self.win.engine.table("summary")
        for c, n in sorted(counts.items()):
            t.add({"Label": doc.name, "Frame": doc.frame + 1, "Type": c + 1, "Count": n})
        self.win.refresh_all()

    def count(self):
        r = self.win.run_op(
            "count_cells", sigma=self.sigma.value(), bg_radius=self.bg_radius.value(),
            method=self.method.currentData(), background=self.background.currentData(),
            split=self.split.isChecked(), tolerance=self.tolerance.value(), min_size=self.min_size.value(),
            max_size=self.max_size.value(), min_circ=self.min_circ.value(), exclude_edges=self.exclude.isChecked(),
            add_to_manager=self.to_manager.isChecked(), all_frames=self.all_frames.isChecked())
        if r:
            self.result.setText(str(r["count"]))
            self.result.setVisible(True)


# ---------------------------------------------------------------------------
class FluorPanel(Panel):
    def __init__(self, win):
        super().__init__(win)
        g = self.group("fluor.intensity")
        v = QVBoxLayout(g)
        v.addWidget(self.label("fluor.hint", "hint", True))
        v.addWidget(self.button("fluor.measure", self.measure, True))
        form = self.advanced()
        v.addWidget(self.col.itemAt(self.col.count() - 2).widget())
        v.addWidget(self.col.itemAt(self.col.count() - 1).widget())
        self.background = self.form_row(form, "param.background", self.combo(["auto", "roi", "value"], "choice.bg_"))
        self.value = self.form_row(form, "param.value", dspin(0.0, -1e9, 1e9, decimals=2))
        self.all_channels = self.T(QCheckBox(), "param.all_channels")
        self.all_channels.setChecked(True)
        form.addRow(self.all_channels)

        g = self.group("coloc.title")
        v = QVBoxLayout(g)
        v.addWidget(self.label("coloc.hint", "hint", True))
        form = QFormLayout()
        self.ch1, self.ch2 = QComboBox(), QComboBox()
        self.form_row(form, "param.ch1", self.ch1)
        self.form_row(form, "param.ch2", self.ch2)
        v.addLayout(form)
        v.addWidget(self.button("coloc.analyze", self.analyze, True))
        self.plot = PlotWidget(min_height=210)
        self.plot.setMaximumHeight(240)
        v.addWidget(self.plot)
        self.stats = QLabel()
        self.stats.setWordWrap(True)
        self.stats.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.stats)
        form = self.advanced()
        v.addWidget(self.col.itemAt(self.col.count() - 2).widget())
        v.addWidget(self.col.itemAt(self.col.count() - 1).widget())
        self.threshold = self.form_row(form, "param.threshold", self.combo(["costes", "otsu", "manual", "none"],
                                                                         "choice.thr_"))
        self.t1 = self.form_row(form, "param.t1", dspin(0.0, -1e9, 1e9, decimals=1))
        self.t2 = self.form_row(form, "param.t2", dspin(0.0, -1e9, 1e9, decimals=1))
        self.col.addStretch(1)
        self._names = None

    def refresh(self):
        doc = self.win.doc()
        names = doc.channel_names() if doc else []
        if names != self._names:
            self._names = names
            for combo, default in ((self.ch1, 0), (self.ch2, 1)):
                combo.clear()
                for i, n in enumerate(names):
                    combo.addItem(n, i)
                combo.setCurrentIndex(min(default, max(len(names) - 1, 0)))
            self.plot.set_data(message=tr("coloc.plot_empty"))
            self.stats.setText("")

    def retranslate(self):
        super().retranslate()
        if not self.stats.text():
            self.plot.set_data(message=tr("coloc.plot_empty"))

    def measure(self):
        self.win.run_op("fluorescence", background=self.background.currentData(), value=self.value.value(),
                        all_channels=self.all_channels.isChecked())

    def analyze(self):
        r = self.win.run_op("colocalization", ch1=self.ch1.currentData() or 0, ch2=self.ch2.currentData() or 0,
                            threshold=self.threshold.currentData(), t1=self.t1.value(), t2=self.t2.value())
        if not r:
            return
        self.plot.set_data(image=r["_hist"], xrange=(0, r["_xmax"]), yrange=(0, r["_ymax"]),
                           xlabel=self.ch1.currentText(), ylabel=self.ch2.currentText(),
                           vlines=[(r["Thr1"], "#ffffff")])
        self.stats.setText(
            f"<b>Pearson r = {r['Pearson r']:.3f}</b> &nbsp; Spearman = {r['Spearman']:.3f}<br>"
            f"M1 = {r['M1']:.3f} &nbsp; M2 = {r['M2']:.3f} &nbsp; MOC = {r['Overlap (MOC)']:.3f}<br>"
            f"ICQ = {r['ICQ']:.3f} &nbsp; {tr('coloc.thresholds')}: {r['Thr1']:.4g} / {r['Thr2']:.4g}")


# ---------------------------------------------------------------------------
class WoundPanel(Panel):
    def __init__(self, win):
        super().__init__(win)
        self.col.addWidget(self.label("wound.hint", "hint", True))
        self.col.addWidget(self.button("wound.measure", self.measure, True))
        self.result = QLabel("")
        self.result.setProperty("role", "big")
        self.result.setAlignment(Qt.AlignCenter)
        self.result.setVisible(False)          # shown once there is a result
        self.col.addWidget(self.result)
        self.plot = PlotWidget(min_height=180)
        self.plot.setMaximumHeight(240)
        self.col.addWidget(self.plot)
        form = self.advanced()
        self.radius = self.form_row(form, "param.radius", spin(8, 2, 100))
        self.sensitivity = self.form_row(form, "param.sensitivity", dspin(1.0, 0.1, 5.0, step=0.1))
        self.min_area = self.form_row(form, "param.min_area", dspin(1.0, 0.0, 50.0, step=0.5, decimals=1))
        self.keep_largest = self.T(QCheckBox(), "param.keep_largest")
        self.all_frames = self.T(QCheckBox(), "param.all_frames")
        self.all_frames.setChecked(True)
        form.addRow(self.keep_largest)
        form.addRow(self.all_frames)
        self.col.addStretch(1)
        self.plot.set_data(message=tr("wound.plot_empty"))
        self._has_plot = False

    def retranslate(self):
        super().retranslate()
        if not self._has_plot:
            self.plot.set_data(message=tr("wound.plot_empty"))

    def measure(self):
        rows = self.win.run_op("wound_healing", radius=self.radius.value(), sensitivity=self.sensitivity.value(),
                               min_area=self.min_area.value(), keep_largest=self.keep_largest.isChecked(),
                               all_frames=self.all_frames.isChecked())
        if not rows:
            return
        doc = self.win.doc()
        cur = next((r for r in rows if r["Frame"] == doc.frame + 1), rows[0])
        self.result.setText(f"{cur['%Area']:.1f}%")
        self.result.setVisible(True)
        if len(rows) > 1:
            self.plot.set_data([{"x": [r["Frame"] for r in rows], "y": [r["Closure %"] for r in rows], "fill": True}],
                               xlabel=tr("wound.frame"), ylabel=tr("wound.closure"))
            self._has_plot = True


# ---------------------------------------------------------------------------
class ResultsPanel(QWidget, Tr):
    def __init__(self, win):
        super().__init__()
        self._tr_setup()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        row = QHBoxLayout()
        self.which = QComboBox()
        self.which.setMinimumWidth(220)
        self.which.currentIndexChanged.connect(lambda *_: self.show_table())
        row.addWidget(self.which)
        self.count = QLabel()
        self.count.setProperty("role", "hint")
        row.addWidget(self.count)
        row.addStretch(1)
        row.addWidget(self.button("results.copy", self.copy))
        row.addWidget(self.button("results.export", self.export, True))
        row.addWidget(self.button("results.clear", self.clear))
        lay.addLayout(row)
        self.model = TableModel(self)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setAlternatingRowColors(True)
        self.view.verticalHeader().setDefaultSectionSize(24)
        lay.addWidget(self.view, 1)
        self._fill()

    def _fill(self):
        eng = self.win.engine
        cur = self.which.currentData() or "results"
        self.which.blockSignals(True)
        self.which.clear()
        for key in eng.TABLES:
            self.which.addItem(f"{tr('table.' + key)}  ({len(eng.tables[key])})", key)
        set_combo(self.which, cur)
        self.which.blockSignals(False)

    def key(self):
        return self.which.currentData() or "results"

    def refresh(self, focus=None):
        self._fill()
        if focus:
            set_combo(self.which, focus)
        self.show_table()

    def retranslate(self):
        super().retranslate()
        self.refresh()

    def show_table(self):
        t = self.win.engine.tables[self.key()]
        self.model.set_table(t)
        self.count.setText(tr("results.rows", n=len(t)))
        if len(t.cols) <= 40:
            self.view.resizeColumnsToContents()
        self.view.scrollToBottom()

    def copy(self):
        QApplication.clipboard().setText(self.win.engine.tables[self.key()].to_tsv())
        self.win.status(tr("results.copied"))

    def export(self):
        t = self.win.engine.tables[self.key()]
        if not len(t):
            self.win.warn(tr("results.empty"))
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("results.export"), self.key() + ".csv", "CSV (*.csv)")
        if path:
            t.to_csv(path)
            self.win.status(tr("results.saved", path=path))

    def clear(self):
        self.win.engine.tables[self.key()].clear()
        self.refresh()


class RecorderPanel(QWidget, Tr):
    def __init__(self, win):
        super().__init__()
        self._tr_setup()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        row = QHBoxLayout()
        row.addWidget(self.label("rec.hint", "hint", True), 1)
        row.addWidget(self.button("rec.copy", lambda: QApplication.clipboard().setText(self.text.toPlainText())))
        row.addWidget(self.button("rec.clear", self.clear))
        row.addWidget(self.button("rec.script", win.show_script))
        row.addWidget(self.button("rec.batch", win.show_batch, True))
        lay.addLayout(row)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(mono_font())
        lay.addWidget(self.text, 1)

    def append(self, line):
        self.text.appendPlainText(line)

    def clear(self):
        self.text.clear()
        self.win._last_roi_sig = None
