"""Main window."""
from __future__ import annotations

import os
import sys
import traceback

import numpy as np
from PySide6.QtCore import QLocale, QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDockWidget, QFileDialog, QHBoxLayout, QLabel,
                               QMainWindow, QMenu, QMessageBox, QSlider, QStackedWidget, QTabWidget, QToolBar,
                               QVBoxLayout, QWidget)

from .. import APP_FULL, APP_NAME, __version__
from ..core import io, measure as ms, samples
from ..core.engine import OPS, Context, Engine, OpError, format_call, script_namespace
from ..core.image import LUT_NAMES
from ..core.roi import Roi
from ..i18n import T, tr
from . import theme
from .canvas import TOOLS, Canvas, flatten
from .dialogs import BatchDialog, BCDialog, HelpDialog, ParamDialog, PlotDialog, ScriptDialog, ThresholdDialog
from .panels import CellPanel, FluorPanel, GelPanel, RecorderPanel, ResultsPanel, RoiPanel, WoundPanel
from .util import Tr

FILE_FILTER = "Images (*.tif *.tiff *.png *.jpg *.jpeg *.bmp *.gif *.webp);;*"
TOOL_KEYS = {"rect": "R", "ellipse": "O", "polygon": "G", "freehand": "F", "line": "L", "point": "P",
             "wand": "W", "hand": "H", "zoom": "Z"}
NO_RECORD = {"select"}


class UiContext(Context):
    """Open images are the tabs of the main window."""

    def __init__(self, win):
        super().__init__()
        self.win = win

    @property
    def docs(self):
        return [v.doc for v in self.win.views()]

    @property
    def current(self):
        return self.win.doc()

    def add(self, doc):
        self.win.add_doc(doc)

    def select(self, key):
        for i, v in enumerate(self.win.views()):
            if key == i or key == v.doc.name:
                self.win.tabs.setCurrentIndex(i)
                return v.doc
        raise OpError("err.no_such_image", name=str(key))


class ImageView(QWidget, Tr):
    """Canvas plus the frame / channel bar."""

    def __init__(self, win, doc):
        super().__init__()
        self._tr_setup()
        self.win, self.doc = win, doc
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.canvas = Canvas(doc)
        lay.addWidget(self.canvas, 1)
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 4, 10, 4)
        self.frame_label = self.label("view.frame")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMaximumWidth(260)
        self.slider.valueChanged.connect(self._frame)
        self.frame_pos = QLabel()
        self.channel_label = self.label("view.channel")
        self.channel = QComboBox()
        self.channel.currentIndexChanged.connect(self._channel)
        self.composite = self.T(QCheckBox(), "view.composite")
        self.composite.toggled.connect(self._composite)
        self.zoom = QLabel()
        self.zoom.setProperty("role", "hint")
        for w in (self.frame_label, self.slider, self.frame_pos, self.channel_label, self.channel, self.composite):
            row.addWidget(w)
        row.addStretch(1)
        row.addWidget(self.zoom)
        lay.addWidget(bar)
        self.canvas.zoomChanged.connect(lambda z: self.zoom.setText(f"{z * 100:.0f}%"))
        self.sync()

    def sync(self):
        doc = self.doc
        for w in (self.slider, self.channel, self.composite):
            w.blockSignals(True)
        multi_f = doc.F > 1
        for w in (self.frame_label, self.slider, self.frame_pos):
            w.setVisible(multi_f)
        self.slider.setRange(0, doc.F - 1)
        self.slider.setValue(doc.frame)
        self.frame_pos.setText(f"{doc.frame + 1} / {doc.F}")
        multi_c = doc.C > 1 and not doc.rgb
        for w in (self.channel_label, self.channel, self.composite):
            w.setVisible(multi_c)
        names = doc.channel_names()
        if [self.channel.itemText(i) for i in range(self.channel.count())] != names:
            self.channel.clear()
            self.channel.addItems(names)
        self.channel.setCurrentIndex(doc.channel)
        self.composite.setChecked(doc.composite)
        for w in (self.slider, self.channel, self.composite):
            w.blockSignals(False)
        self.zoom.setText(f"{self.canvas.zoom() * 100:.0f}%")

    def refresh(self):
        self.sync()
        self.canvas.refresh()

    def _frame(self, v):
        self.doc.frame = v
        self.win.view_changed()

    def _channel(self, i):
        if i >= 0:
            self.doc.channel = i
            self.win.view_changed()

    def _composite(self, on):
        self.doc.composite = on
        self.win.view_changed()


class MainWindow(QMainWindow, Tr):
    def __init__(self):
        super().__init__()
        self._tr_setup()
        self.settings = QSettings("OpenResearch", APP_NAME)
        self.engine = Engine()
        self.ctx = UiContext(self)
        self.params_memory = {}
        self._last_roi_sig = None
        self._dialogs = []
        self.bc_dlg = self.thr_dlg = None
        self.tool = "rect"
        T.set_language(self.settings.value("lang") or T.match(QLocale.system().name()))
        self.theme_name = self.settings.value("theme") or "light"
        theme.apply_theme(QApplication.instance(), self.theme_name)
        self.setWindowIcon(theme.app_icon())
        self.setAcceptDrops(True)
        self.resize(1380, 860)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(lambda *_: self.refresh_all())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._welcome())
        self.stack.addWidget(self.tabs)
        self.setCentralWidget(self.stack)

        self.toolbar = QToolBar()
        self.toolbar.setObjectName("tools")
        self.toolbar.setMovable(False)
        self.toolbar.setOrientation(Qt.Vertical)
        self.addToolBar(Qt.LeftToolBarArea, self.toolbar)
        self.tool_group = QActionGroup(self)
        self.tool_actions = {}
        for name in TOOLS:
            a = QAction(self)
            a.setCheckable(True)
            a.setShortcut(QKeySequence(TOOL_KEYS[name]))
            a.triggered.connect(lambda *_, n=name: self.set_tool(n))
            self.tool_group.addAction(a)
            self.toolbar.addAction(a)
            self.tool_actions[name] = a
        self.tool_actions["rect"].setChecked(True)

        self.roi_panel, self.gel_panel = RoiPanel(self), GelPanel(self)
        self.cell_panel, self.fluor_panel, self.wound_panel = CellPanel(self), FluorPanel(self), WoundPanel(self)
        self.panels = [("panel.roi", self.roi_panel), ("panel.gel", self.gel_panel), ("panel.cells", self.cell_panel),
                       ("panel.fluor", self.fluor_panel), ("panel.wound", self.wound_panel)]
        self.side_tabs = QTabWidget()
        self.side_tabs.setUsesScrollButtons(True)
        for key, p in self.panels:
            self.side_tabs.addTab(p, tr(key))
        self.side_dock = QDockWidget()
        self.side_dock.setObjectName("side")
        self.side_dock.setWidget(self.side_tabs)
        self.side_dock.setMinimumWidth(360)
        self.side_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.RightDockWidgetArea, self.side_dock)

        self.results_panel, self.recorder = ResultsPanel(self), RecorderPanel(self)
        self.bottom_tabs = QTabWidget()
        self.bottom_tabs.addTab(self.results_panel, tr("panel.results"))
        self.bottom_tabs.addTab(self.recorder, tr("panel.recorder"))
        self.bottom_dock = QDockWidget()
        self.bottom_dock.setObjectName("bottom")
        self.bottom_dock.setWidget(self.bottom_tabs)
        self.bottom_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.bottom_dock)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)
        self.resizeDocks([self.bottom_dock], [250], Qt.Vertical)
        self.resizeDocks([self.side_dock], [430], Qt.Horizontal)

        self.pos_label, self.info_label = QLabel(), QLabel()
        self.statusBar().addPermanentWidget(self.pos_label)
        self.statusBar().addPermanentWidget(self.info_label)

        self.retranslate_all()
        if self.settings.value("geometry"):
            self.restoreGeometry(self.settings.value("geometry"))

    # ------------------------------------------------------------------
    # structure
    # ------------------------------------------------------------------
    def _welcome(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.addStretch(2)
        icon = QLabel()
        icon.setPixmap(theme.app_icon().pixmap(96, 96))
        icon.setAlignment(Qt.AlignCenter)
        outer.addWidget(icon)
        title = QLabel(APP_NAME)
        title.setProperty("role", "title")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)
        sub = self.label("welcome.subtitle", "hint")
        sub.setAlignment(Qt.AlignCenter)
        outer.addWidget(sub)
        outer.addSpacing(14)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.button("welcome.open", self.open_dialog, True))
        row.addStretch(1)
        outer.addLayout(row)
        outer.addSpacing(10)
        hint = self.label("welcome.samples", "hint")
        hint.setAlignment(Qt.AlignCenter)
        outer.addWidget(hint)
        row = QHBoxLayout()
        row.addStretch(1)
        for name in samples.SAMPLES:
            row.addWidget(self.button("sample." + name, lambda n=name: self.open_sample(n)))
        row.addStretch(1)
        outer.addLayout(row)
        outer.addSpacing(10)
        drop = self.label("welcome.drop", "hint")
        drop.setAlignment(Qt.AlignCenter)
        outer.addWidget(drop)
        outer.addSpacing(18)
        # the language switch is shown here too, so it can be found whatever language is active
        row = QHBoxLayout()
        row.addStretch(1)
        self.lang_combo = QComboBox()
        for code, name in T.available():
            self.lang_combo.addItem(name, code)
        self.lang_combo.setCurrentIndex(max(0, self.lang_combo.findData(T.lang)))
        self.lang_combo.currentIndexChanged.connect(lambda *_: self.set_language(self.lang_combo.currentData()))
        row.addWidget(QLabel("Language / \u8a9e\u8a00"))
        row.addWidget(self.lang_combo)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(3)
        return w

    def _act(self, menu, key, slot, shortcut=None, checkable=False, checked=False, text=None):
        a = QAction(text or tr(key), self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if checkable:
            a.setCheckable(True)
            a.setChecked(checked)
            a.toggled.connect(slot)
        else:
            a.triggered.connect(lambda *_: slot())
        menu.addAction(a)
        self._menu_actions.append(a)
        return a

    def _op(self, menu, name, shortcut=None):
        dialog = any(p["type"] != "raw" for p in OPS[name].params)
        return self._act(menu, None, lambda: self.ask_op(name), shortcut,
                         text=tr("op." + name) + ("…" if dialog else ""))

    def _build_menus(self):
        mb = self.menuBar()
        # menus are rebuilt on every language change: drop the old actions so shortcuts stay unique
        for a in getattr(self, "_menu_actions", []):
            a.setShortcut(QKeySequence())
            a.deleteLater()
        self._menu_actions = []
        for old in mb.findChildren(QMenu, options=Qt.FindDirectChildrenOnly):
            old.deleteLater()
        mb.clear()
        A, O = self._act, self._op

        m = mb.addMenu(tr("menu.file"))
        A(m, "file.open", self.open_dialog, "Ctrl+O")
        sm = m.addMenu(tr("file.samples"))
        for name in samples.SAMPLES:
            A(sm, "sample." + name, lambda n=name: self.open_sample(n))
        A(m, "file.sequence", self.import_sequence)
        self.recent_menu = m.addMenu(tr("file.recent"))
        self._fill_recent()
        m.addSeparator()
        A(m, "file.save", self.save, "Ctrl+S")
        A(m, "file.save_as", self.save_as, "Ctrl+Shift+S")
        A(m, "file.export_view", self.export_view)
        m.addSeparator()
        A(m, "file.close", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
        A(m, "file.close_all", self.close_all)
        A(m, "file.quit", self.close, "Ctrl+Q")

        m = mb.addMenu(tr("menu.edit"))
        self.undo_action = A(m, "edit.undo", self.undo, "Ctrl+Z")
        self.redo_action = A(m, "edit.redo", self.redo, "Ctrl+Shift+Z")
        m.addSeparator()
        A(m, "edit.select_all", self.select_all, "Ctrl+A")
        A(m, "edit.select_none", lambda: self.set_roi(None), "Ctrl+Shift+A")
        A(m, "edit.add_roi", self.roi_panel.add, "Ctrl+T")
        m.addSeparator()
        O(m, "crop", "Ctrl+Shift+X")
        O(m, "duplicate", "Ctrl+Shift+D")
        O(m, "clear")
        O(m, "clear_outside")
        O(m, "invert", "Ctrl+Shift+I")
        m.addSeparator()
        O(m, "clear_overlay")

        m = mb.addMenu(tr("menu.image"))
        sm = m.addMenu(tr("image.type"))
        for n in ("to_8bit", "to_16bit", "to_32bit", "to_rgb"):
            O(sm, n)
        sm = m.addMenu(tr("image.adjust"))
        A(sm, "image.bc", self.show_bc, "Ctrl+Shift+C")
        A(sm, "image.threshold", self.show_threshold, "Ctrl+Shift+T")
        A(sm, "image.auto_contrast", lambda: self.run_op("auto_contrast"))
        sm = m.addMenu(tr("image.color"))
        O(sm, "split_channels")
        O(sm, "merge_channels")
        lut = sm.addMenu(tr("image.lut"))
        for n in LUT_NAMES:
            A(lut, "lut." + n, lambda n=n: self.run_op("set_lut", name=n))
        sm = m.addMenu(tr("image.stacks"))
        for n in ("images_to_stack", "stack_to_images", "z_project"):
            O(sm, n)
        A(sm, "image.next_frame", lambda: self.step_frame(1), ".")
        A(sm, "image.prev_frame", lambda: self.step_frame(-1), ",")
        sm = m.addMenu(tr("image.transform"))
        for n in ("flip_horizontal", "flip_vertical", "rotate_right", "rotate_left", "rotate", "scale"):
            O(sm, n)
        m.addSeparator()
        O(m, "set_scale")
        O(m, "scale_bar")
        O(m, "rename")
        A(m, "image.info", self.show_info, "Ctrl+I")

        m = mb.addMenu(tr("menu.process"))
        for n in ("smooth", "sharpen", "find_edges", "enhance_contrast", "equalize", "clahe"):
            O(m, n)
        sm = m.addMenu(tr("process.filters"))
        for n in ("gaussian", "median", "mean", "minimum", "maximum", "variance", "unsharp", "bandpass"):
            O(sm, n)
        O(m, "subtract_background")
        sm = m.addMenu(tr("process.math"))
        for n in ("add", "subtract", "multiply", "divide", "gamma", "log", "sqrt"):
            O(sm, n)
        sm = m.addMenu(tr("process.binary"))
        for n in ("make_binary", "erode", "dilate", "open", "close", "fill_holes", "outline", "skeletonize",
                  "watershed", "distance_map"):
            O(sm, n)
        O(m, "image_calculator")
        m.addSeparator()
        A(m, "process.whole_stack", self._set_whole_stack, checkable=True, checked=self.engine.whole_stack)

        m = mb.addMenu(tr("menu.analyze"))
        O(m, "measure", "Ctrl+M")
        O(m, "measure_all")
        O(m, "analyze_particles")
        A(m, "analyze.histogram", self.show_histogram, "Ctrl+H")
        A(m, "analyze.profile", self.show_profile, "Ctrl+K")
        m.addSeparator()
        for i, (key, _) in enumerate(self.panels[1:], 1):
            A(m, key, lambda i=i: self.show_panel(i))
        m.addSeparator()
        A(m, "analyze.script", self.show_script)
        A(m, "analyze.batch", self.show_batch)

        m = mb.addMenu(tr("menu.view"))
        A(m, "view.zoom_in", lambda: self.zoom_by(1.25), "Ctrl+=")
        A(m, "view.zoom_out", lambda: self.zoom_by(0.8), "Ctrl+-")
        A(m, "view.fit", lambda: self.view() and self.view().canvas.fit(), "Ctrl+0")
        A(m, "view.actual", lambda: self.view() and self.view().canvas.set_zoom(1.0), "Ctrl+1")
        m.addSeparator()
        m.addAction(self.side_dock.toggleViewAction())
        m.addAction(self.bottom_dock.toggleViewAction())
        sm = m.addMenu(tr("view.theme"))
        theme_group = QActionGroup(sm)
        for n in ("dark", "light"):
            A(sm, "theme." + n, lambda on, n=n: on and self.set_theme(n), checkable=True,
              checked=self.theme_name == n).setActionGroup(theme_group)

        title = tr("menu.language") + ("" if T.lang == "en" else " (Language)")
        m = mb.addMenu(title)
        lang_group = QActionGroup(m)
        for code, name in T.available():
            A(m, None, lambda on, c=code: on and self.set_language(c), checkable=True,
              checked=code == T.lang, text=name).setActionGroup(lang_group)

        m = mb.addMenu(tr("menu.help"))
        A(m, "help.quickstart", self.show_help, "F1")
        A(m, "help.about", self.show_about)

    def retranslate_all(self):
        self.retranslate()
        self._build_menus()
        for name, a in self.tool_actions.items():
            a.setIcon(theme.tool_icon(name))
            a.setText(tr("tool." + name))
            a.setToolTip(f"{tr('tool.' + name)}  [{TOOL_KEYS[name]}]\n{tr('tooltip.' + name)}")
        for i, (key, p) in enumerate(self.panels):
            self.side_tabs.setTabText(i, tr(key))
            p.retranslate()
        self.bottom_tabs.setTabText(0, tr("panel.results"))
        self.bottom_tabs.setTabText(1, tr("panel.recorder"))
        self.results_panel.retranslate()
        self.recorder.retranslate()
        self.side_dock.setWindowTitle(tr("dock.analysis"))
        self.bottom_dock.setWindowTitle(tr("dock.results"))
        for v in self.views():
            v.retranslate()
        for d in (self.bc_dlg, self.thr_dlg):
            if d is not None:
                d.close()
        self.bc_dlg = self.thr_dlg = None
        self.lang_combo.blockSignals(True)
        self.lang_combo.setCurrentIndex(max(0, self.lang_combo.findData(T.lang)))
        self.lang_combo.blockSignals(False)
        self.refresh_all()

    def set_language(self, code):
        if code == T.lang:
            return
        T.set_language(code)
        self.settings.setValue("lang", code)
        self.retranslate_all()

    def set_theme(self, name):
        if name == self.theme_name:
            return
        self.theme_name = name
        self.settings.setValue("theme", name)
        theme.apply_theme(QApplication.instance(), name)
        for a_name, a in self.tool_actions.items():
            a.setIcon(theme.tool_icon(a_name))
        self.refresh_all()
        for w in self.findChildren(QWidget):
            w.update()

    # ------------------------------------------------------------------
    # access helpers
    # ------------------------------------------------------------------
    def views(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def view(self):
        return self.tabs.currentWidget()

    def doc(self):
        v = self.view()
        return v.doc if v is not None else None

    def status(self, text):
        self.statusBar().showMessage(text, 6000)

    def warn(self, text):
        QMessageBox.warning(self, APP_NAME, text)

    def set_tool(self, name):
        self.tool = name
        self.tool_actions[name].setChecked(True)
        for v in self.views():
            v.canvas.set_tool(name)

    def set_roi(self, roi):
        v = self.view()
        if v is not None:
            v.canvas.set_roi(roi)

    def select_all(self):
        d = self.doc()
        if d is not None:
            self.set_roi(Roi("rect", [(0, 0), (d.W, d.H)]))

    def zoom_by(self, f):
        v = self.view()
        if v is not None:
            v.canvas.set_zoom(v.canvas.zoom() * f)

    def step_frame(self, d):
        doc = self.doc()
        if doc is not None and doc.F > 1:
            doc.frame = (doc.frame + d) % doc.F
            self.view_changed()

    def show_panel(self, i):
        self.side_dock.show()
        self.side_tabs.setCurrentIndex(i)

    def _set_whole_stack(self, on):
        self.engine.whole_stack = bool(on)

    # ------------------------------------------------------------------
    # documents
    # ------------------------------------------------------------------
    def add_doc(self, doc):
        names = {v.doc.name for v in self.views()}
        base, n = doc.name, 2
        while doc.name in names:
            doc.name = f"{base} ({n})"
            n += 1
        view = ImageView(self, doc)
        view.canvas.set_tool(self.tool)
        view.canvas.category = self.cell_panel.category.currentData() or 0
        view.canvas.show_all = self.roi_panel.show_all.isChecked()
        view.canvas.mouseMoved.connect(self._mouse_moved)
        view.canvas.roiChanged.connect(self._roi_changed)
        self.tabs.addTab(view, doc.name)
        self.tabs.setCurrentWidget(view)
        self.refresh_all()

    def open_paths(self, paths):
        for p in paths:
            try:
                QApplication.setOverrideCursor(Qt.WaitCursor)
                doc = io.load_image(p)
            except Exception as e:  # noqa: BLE001 - any unreadable file is reported to the user
                QApplication.restoreOverrideCursor()
                self.warn(tr("err.open", path=os.path.basename(str(p)), msg=str(e)))
                continue
            QApplication.restoreOverrideCursor()
            self.add_doc(doc)
            self._add_recent(str(p))

    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("file.open"), self.settings.value("dir") or "", FILE_FILTER)
        if paths:
            self.settings.setValue("dir", os.path.dirname(paths[0]))
            self.open_paths(paths)

    def open_sample(self, name):
        self.add_doc(samples.SAMPLES[name]())
        self.show_panel({"blot": 1, "nuclei": 2, "fluorescence": 3, "wound": 4}[name])

    def import_sequence(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("file.sequence"), self.settings.value("dir") or "", FILE_FILTER)
        if len(paths) > 1:
            try:
                self.add_doc(io.load_sequence(paths))
            except Exception:  # noqa: BLE001
                self.warn(tr("err.size_mismatch"))

    def _add_recent(self, path):
        rec = [p for p in (self.settings.value("recent") or []) if p != path]
        self.settings.setValue("recent", [path] + rec[:9])
        self._fill_recent()

    def _fill_recent(self):
        self.recent_menu.clear()
        rec = self.settings.value("recent") or []
        if isinstance(rec, str):
            rec = [rec]
        for p in rec:
            self._act(self.recent_menu, None, lambda p=p: self.open_paths([p]), text=os.path.basename(p))
        self.recent_menu.setEnabled(bool(rec))

    def save(self):
        doc = self.doc()
        if doc is None:
            return False
        if not doc.path or not doc.path.lower().endswith((".tif", ".tiff")):
            return self.save_as()
        return self._write(doc, doc.path)

    def save_as(self):
        doc = self.doc()
        if doc is None:
            return False
        start = os.path.join(self.settings.value("dir") or "", os.path.splitext(doc.name)[0] + ".tif")
        path, _ = QFileDialog.getSaveFileName(self, tr("file.save_as"), start,
                                              "TIFF (*.tif);;PNG (*.png);;JPEG (*.jpg);;BMP (*.bmp)")
        if not path:
            return False
        if not os.path.splitext(path)[1]:
            path += ".tif"
        return self._write(doc, path)

    def _write(self, doc, path):
        try:
            io.save_image(doc, path)
        except Exception as e:  # noqa: BLE001
            self.warn(tr("err.save", msg=str(e)))
            return False
        if path.lower().endswith((".tif", ".tiff")):
            doc.path, doc.name, doc.modified = path, os.path.basename(path), False
        self.status(tr("status.saved", path=path))
        self.refresh_all()
        return True

    def export_view(self):
        doc = self.doc()
        if doc is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("file.export_view"), os.path.splitext(doc.name)[0] + "_view.png",
                                              "PNG (*.png);;JPEG (*.jpg)")
        if path:
            if not os.path.splitext(path)[1]:
                path += ".png"
            flatten(doc).save(path)
            self.status(tr("status.saved", path=path))

    def close_tab(self, i):
        v = self.tabs.widget(i)
        if v is None:
            return True
        if v.doc.modified:
            box = QMessageBox(QMessageBox.Question, APP_NAME, tr("close.ask", name=v.doc.name), parent=self)
            save = box.addButton(tr("close.save"), QMessageBox.AcceptRole)
            box.addButton(tr("close.discard"), QMessageBox.DestructiveRole)
            cancel = box.addButton(tr("dlg.cancel"), QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is cancel:
                return False
            if box.clickedButton() is save:
                self.tabs.setCurrentIndex(i)
                if not self.save():
                    return False
        self.tabs.removeTab(i)
        v.deleteLater()
        self.refresh_all()
        return True

    def close_all(self):
        while self.tabs.count():
            if not self.close_tab(self.tabs.count() - 1):
                return False
        return True

    def undo(self):
        d = self.doc()
        if d is not None and d.undo():
            self.refresh_all()

    def redo(self):
        d = self.doc()
        if d is not None and d.redo():
            self.refresh_all()

    # ------------------------------------------------------------------
    # operations
    # ------------------------------------------------------------------
    def run_op(self, name, /, **params):
        """Run an operation on the current image, record it, and refresh the UI."""
        doc = self.doc()
        if doc is None:
            self.warn(tr("err.no_image"))
            return None
        v = self.view()
        v.canvas.preview = None
        before = {k: len(t) for k, t in self.engine.tables.items()}
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._record_roi(doc)
            result = self.engine.run(self.ctx, name, **params)
        except OpError as e:
            QApplication.restoreOverrideCursor()
            self.refresh_all()
            self.warn(tr(e.key, **e.kw))
            return None
        except Exception as e:  # noqa: BLE001 - never let an operation crash the application
            QApplication.restoreOverrideCursor()
            traceback.print_exc()
            self.refresh_all()
            self.warn(tr("err.failed", msg=f"{type(e).__name__}: {e}"))
            return None
        QApplication.restoreOverrideCursor()
        if name not in NO_RECORD:
            self.record(name, params)
        grew = [k for k, t in self.engine.tables.items() if len(t) > before[k]]
        focus = next((k for k in grew if k != "summary"), grew[0] if grew else None)
        self.refresh_all(focus)
        if focus:
            self.bottom_dock.show()
            self.bottom_tabs.setCurrentIndex(0)
        return result if result is not None else True

    def ask_op(self, name):
        """Show the parameter dialog for an operation (if it has one), then run it."""
        op = OPS[name]
        doc = self.doc()
        if doc is None:
            self.warn(tr("err.no_image"))
            return
        specs = [p for p in op.params if p["type"] != "raw"]
        if name == "duplicate" and doc.F == 1:
            specs = []
        if not specs:
            self.run_op(name)
            return
        values = dict(self.params_memory.get(name, {}))
        if name == "set_scale":
            roi = doc.active_roi
            values = {"distance": roi.length() if roi is not None and roi.kind == "line" else 1.0 / doc.pixel_size,
                      "known": 1.0, "unit": doc.unit if doc.unit != "px" else "µm"}
        elif name == "rename":
            values = {"name": doc.name}
        elif name == "scale_bar" and name not in self.params_memory:
            target = doc.W * doc.pixel_size * 0.2
            nice = min((m * 10 ** e for e in range(-3, 7) for m in (1, 2, 5)), key=lambda x: abs(x - target))
            values = {"length": nice, "thickness": max(2, doc.H // 120)}
        image_params = [p["name"] for p in specs if p["type"] == "image"]
        if image_params:
            # suggest the current image first, then other open images of the same size and type
            same = [d.name for d in self.ctx.docs if d is not doc and d.data.shape[2:] == doc.data.shape[2:]
                    and d.data.dtype == doc.data.dtype]
            names = [doc.name] + same
            for i, pname in enumerate(image_params):
                values[pname] = names[min(i, len(names) - 1)]
        preview = (lambda vals: self.preview_op(name, vals)) if op.kind in ("plane", "binary") else None
        dlg = ParamDialog(self, tr("op." + name), specs, values, preview)
        ok = dlg.exec()
        self.preview_op(name, None)
        if ok:
            vals = dlg.values()
            self.params_memory[name] = vals
            self.run_op(name, **vals)

    def preview_op(self, name, vals):
        v = self.view()
        if v is None:
            return
        if vals is None:
            if v.canvas.preview is not None:
                v.canvas.set_preview(None)
            return
        tmp_ctx = Context()
        tmp_ctx.add(v.doc.frame_doc())
        eng = Engine()
        try:
            eng.run(tmp_ctx, name, **vals)
            v.canvas.set_preview(tmp_ctx.current.render(0))
        except Exception:  # noqa: BLE001 - a failed preview is simply not shown
            v.canvas.set_preview(None)

    def _record_roi(self, doc):
        sig = doc.active_roi.signature() if doc.active_roi is not None else None
        if sig != self._last_roi_sig:
            self._last_roi_sig = sig
            if sig is None:
                self.recorder.append("roi()")
            else:
                self.recorder.append(f'roi("{sig[0]}", {[tuple(p) for p in sig[1]]})')

    def record(self, name, params):
        self.recorder.append(format_call(name, params))

    def recorded_script(self):
        return self.recorder.text.toPlainText()

    def run_script(self, code, log):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            exec(compile(code, "<script>", "exec"), script_namespace(self.engine, self.ctx, log))
            ok, msg = True, ""
        except OpError as e:
            ok, msg = False, tr(e.key, **e.kw)
        except Exception:  # noqa: BLE001 - show the script error to its author
            ok, msg = False, traceback.format_exc(limit=-1)
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh_all()
        return ok, msg

    # ------------------------------------------------------------------
    # refresh
    # ------------------------------------------------------------------
    def refresh_canvas(self):
        v = self.view()
        if v is not None:
            v.canvas.refresh()

    def view_changed(self):
        """Frame, channel or composite mode changed."""
        v = self.view()
        if v is not None:
            v.refresh()
        for d in (self.bc_dlg, self.thr_dlg):
            if d is not None and d.isVisible():
                d.refresh()
        self.gel_panel.update_plot()
        self._update_info()

    def refresh_all(self, focus_table=None):
        if not hasattr(self, "results_panel"):
            return
        self.stack.setCurrentIndex(1 if self.tabs.count() else 0)
        for i, v in enumerate(self.views()):
            self.tabs.setTabText(i, v.doc.name + (" *" if v.doc.modified else ""))
        v = self.view()
        if v is not None:
            v.refresh()
        for _, p in self.panels:
            p.refresh()
        self.results_panel.refresh(focus_table)
        for d in (self.bc_dlg, self.thr_dlg):
            if d is not None and d.isVisible():
                d.refresh()
        doc = self.doc()
        self.undo_action.setEnabled(bool(doc and doc.undo_stack))
        self.redo_action.setEnabled(bool(doc and doc.redo_stack))
        self.setWindowTitle(f"{doc.name} — {APP_NAME}" if doc else f"{APP_NAME} — {APP_FULL}")
        self._update_info()

    def _update_info(self):
        doc = self.doc()
        if doc is None:
            self.info_label.setText("")
            self.pos_label.setText("")
            return
        parts = [f"{doc.W} × {doc.H} px", doc.type_label()]
        if doc.C > 1 and not doc.rgb:
            parts.append(tr("info.channels", n=doc.C))
        if doc.F > 1:
            parts.append(tr("info.frames", n=doc.F))
        parts.append(f"1 px = {doc.pixel_size:.4g} {doc.unit}" if doc.unit != "px" else tr("info.uncalibrated"))
        self.info_label.setText("   |   ".join(parts))

    def _mouse_moved(self, x, y):
        doc = self.doc()
        if doc is None:
            return
        ix, iy = int(np.floor(x)), int(np.floor(y))
        if not (0 <= ix < doc.W and 0 <= iy < doc.H):
            self.pos_label.setText("")
            return
        vals = doc.data[doc.frame, :, iy, ix]
        val = ", ".join(f"{v:.4g}" if doc.data.dtype == np.float32 else str(int(v)) for v in vals)
        text = f"x={ix}, y={iy}"
        if doc.unit != "px":
            text += f"  ({ix * doc.pixel_size:.2f}, {iy * doc.pixel_size:.2f} {doc.unit})"
        self.pos_label.setText(f"{text}   {tr('status.value')}={val}")

    def _roi_changed(self):
        self.roi_panel.update_info()
        self.cell_panel.refresh()

    # ------------------------------------------------------------------
    # tool windows
    # ------------------------------------------------------------------
    def _need_doc(self):
        if self.doc() is None:
            self.warn(tr("err.no_image"))
            return False
        return True

    def show_bc(self):
        if self._need_doc():
            if self.bc_dlg is None:
                self.bc_dlg = BCDialog(self)
            self.bc_dlg.refresh()
            self.bc_dlg.show()
            self.bc_dlg.raise_()

    def show_threshold(self):
        if self._need_doc():
            if self.thr_dlg is None:
                self.thr_dlg = ThresholdDialog(self)
            else:
                self.thr_dlg.ensure()
            self.thr_dlg.show()
            self.thr_dlg.raise_()

    def _keep(self, dlg):
        self._dialogs = [d for d in self._dialogs if d.isVisible()] + [dlg]
        dlg.show()
        return dlg

    def show_histogram(self):
        if not self._need_doc():
            return
        doc = self.doc()
        roi = doc.active_roi
        mask = roi.mask((doc.H, doc.W)) if roi is not None and roi.is_area else None
        dlg = PlotDialog(self, f"{tr('analyze.histogram')} — {doc.name}")
        g = doc.gray()
        vals = g[mask] if mask is not None else g.ravel()
        if vals.size == 0:
            return
        vrange = (0.0, 255.0) if (doc.rgb or doc.data.dtype == np.uint8) else None
        hist, edges = ms.histogram(vals, 256, vrange)
        series = [{"x": edges[:-1], "y": hist, "bars": True, "color": theme.C["muted"]}]
        dlg.columns = {"bin_start": edges[:-1], "count": hist}
        if doc.rgb:
            series = []
            for c, col in enumerate(("#ff5d5d", "#4cd27b", "#5aa9ff")):
                p = doc.data[doc.frame, c]
                h, _ = ms.histogram(p[mask] if mask is not None else p.ravel(), 256, vrange)
                series.append({"x": edges[:-1], "y": h, "color": col})
                dlg.columns["RGB"[c]] = h

        def draw():
            dlg.plot.set_data(series, xrange=(float(edges[0]), float(edges[-1])), logy=dlg.log.isChecked(),
                              xlabel=tr("hist.value"), ylabel=tr("hist.count"))
        dlg.log.toggled.connect(lambda *_: draw())
        draw()
        mode = float(edges[int(np.argmax(hist))])
        dlg.info.setText(tr("hist.stats", n=int(vals.size), mean=f"{vals.mean():.3f}", sd=f"{vals.std():.3f}",
                            min=f"{vals.min():.4g}", max=f"{vals.max():.4g}", mode=f"{mode:.4g}"))
        self._keep(dlg)

    def show_profile(self):
        if not self._need_doc():
            return
        doc = self.doc()
        roi = doc.active_roi
        if roi is None or roi.kind not in ("line", "rect"):
            self.warn(tr("err.need_line"))
            return
        x, y = ms.roi_profile(doc, roi)
        if y.size == 0:
            return
        dlg = PlotDialog(self, f"{tr('analyze.profile')} — {doc.name}")
        dlg.columns = {f"distance ({doc.unit})": x, "value": y}

        def draw():
            dlg.plot.set_data([{"x": x, "y": y}], logy=dlg.log.isChecked(), yrange=None if dlg.log.isChecked() else
                              (float(y.min()), float(y.max()) + (float(np.ptp(y)) * 0.06 or 1.0)),
                              xlabel=tr("profile.distance", unit=doc.unit), ylabel=tr("hist.value"))
        dlg.log.toggled.connect(lambda *_: draw())
        draw()
        dlg.info.setText(tr("profile.stats", n=int(y.size), mean=f"{y.mean():.3f}", min=f"{y.min():.4g}",
                            max=f"{y.max():.4g}"))
        self._keep(dlg)

    def show_info(self):
        if not self._need_doc():
            return
        doc = self.doc()
        g = doc.gray()
        rows = [(tr("info.name"), doc.name), (tr("info.path"), doc.path or "–"),
                (tr("info.size"), f"{doc.W} × {doc.H} px"), (tr("info.type"), doc.type_label()),
                (tr("info.channels_label"), str(doc.C)), (tr("info.frames_label"), str(doc.F)),
                (tr("info.calibration"), f"1 px = {doc.pixel_size:.6g} {doc.unit}"),
                (tr("info.range"), f"{float(g.min()):.6g} – {float(g.max()):.6g}"),
                (tr("info.memory"), f"{doc.data.nbytes / 1e6:.1f} MB")]
        html = "<table cellpadding='5'>" + "".join(f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in rows) + "</table>"
        self._keep(HelpDialog(self, tr("image.info"), html)).resize(520, 360)

    def show_script(self):
        self._keep(ScriptDialog(self))

    def show_batch(self):
        self._keep(BatchDialog(self))

    def show_help(self):
        self._keep(HelpDialog(self, tr("help.quickstart"), tr("help.html")))

    def show_about(self):
        html = (f"<h2>{APP_NAME} {__version__}</h2><p><b>{APP_FULL}</b></p><p>{tr('about.text')}</p>"
                f"<p>{tr('about.libs')}: NumPy, SciPy, scikit-image, tifffile, Pillow, Qt for Python (PySide6).</p>"
                f"<p>{tr('about.languages')}: {', '.join(n for _, n in T.available())}</p>")
        self._keep(HelpDialog(self, tr("help.about"), html)).resize(520, 380)

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.open_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    def closeEvent(self, e):
        dirty = [v.doc.name for v in self.views() if v.doc.modified]
        if dirty:
            box = QMessageBox(QMessageBox.Question, APP_NAME, tr("quit.ask", n=len(dirty)), parent=self)
            yes = box.addButton(tr("quit.yes"), QMessageBox.DestructiveRole)
            box.addButton(tr("dlg.cancel"), QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not yes:
                e.ignore()
                return
        self.settings.setValue("geometry", self.saveGeometry())
        e.accept()


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("OpenResearch")
    win = MainWindow()
    win.show()
    if "--selftest" in argv:
        return selftest(app, win)
    files = [a for a in argv[1:] if os.path.isfile(a)]
    if files:
        win.open_paths(files)
    return app.exec()


def selftest(app, win):
    """Verify an installation: run each analysis module on its sample and check the known answers."""
    checks = []
    try:
        for lang, _ in T.available():
            win.set_language(lang)
        win.open_sample("nuclei")
        checks.append(("cell count", win.engine.run(win.ctx, "count_cells")["count"] == samples.NUCLEI_COUNT))
        win.open_sample("blot")
        win.engine.run(win.ctx, "gel", strips=[("t", (30, 75, 530, 115)), ("c", (30, 185, 530, 225))], lanes=6,
                       control="c")
        fold = [r["Fold change"] for r in win.engine.tables["gel"].rows if r["Strip"] == "t"]
        checks.append(("western blot", len(fold) == 6 and all(abs(a - b) < 0.03 for a, b in
                                                              zip(fold, samples.BLOT_TARGET))))
        win.open_sample("fluorescence")
        checks.append(("colocalization", 0.4 < win.engine.run(win.ctx, "colocalization")["Pearson r"] < 0.7))
        win.open_sample("wound")
        rows = win.engine.run(win.ctx, "wound_healing")
        checks.append(("wound healing", abs(rows[0]["%Area"] - 100 * samples.WOUND_WIDTHS[0] / 640) < 1.0))
        app.processEvents()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        checks.append(("run", False))
    report = "\n".join(f"{'ok  ' if ok else 'FAIL'} {name}" for name, ok in checks)
    print(report)
    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":      # a windowed build has no console to print to
        QMessageBox.information(win, f"{APP_NAME} self-test", report)
    for v in win.views():
        v.doc.modified = False
    win.close()
    return 0 if all(ok for _, ok in checks) else 1
