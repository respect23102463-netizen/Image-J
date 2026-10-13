"""Small UI helpers shared by panels and dialogs."""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLabel, QPushButton, QSpinBox

from ..core.results import fmt
from ..i18n import T, tr


class Tr:
    """Mixin: register widgets with translation keys so the UI can switch language live."""

    def _tr_setup(self):
        self._tr_items = []
        self._tr_combos = []

    def T(self, widget, key, attr="setText"):
        self._tr_items.append((widget, key, attr))
        getattr(widget, attr)(tr(key))
        return widget

    def label(self, key, role=None, wrap=False):
        lab = self.T(QLabel(), key)
        if role:
            lab.setProperty("role", role)
        lab.setWordWrap(wrap)
        return lab

    def button(self, key, slot, primary=False, tip=None):
        b = self.T(QPushButton(), key)
        if primary:
            b.setProperty("primary", True)
        if tip:
            self.T(b, tip, "setToolTip")
        b.clicked.connect(lambda *_: slot())
        return b

    def combo(self, values, prefix="choice.", slot=None):
        """Combo whose items are translated; ``currentData()`` gives the raw value."""
        c = QComboBox()
        for v in values:
            c.addItem(T.opt(prefix + str(v), str(v)), v)
        self._tr_combos.append((c, prefix))
        if slot:
            c.currentIndexChanged.connect(lambda *_: slot())
        return c

    def retranslate(self):
        for w, key, attr in self._tr_items:
            getattr(w, attr)(tr(key))
        for c, prefix in self._tr_combos:
            for i in range(c.count()):
                v = c.itemData(i)
                c.setItemText(i, T.opt(prefix + str(v), str(v)))


def spin(value, lo, hi, slot=None, step=1):
    s = QSpinBox()
    s.setRange(int(lo), int(hi))
    s.setSingleStep(step)
    s.setValue(int(value))
    if slot:
        s.valueChanged.connect(lambda *_: slot())
    return s


def dspin(value, lo, hi, slot=None, step=None, decimals=2):
    s = QDoubleSpinBox()
    s.setDecimals(decimals)
    s.setRange(float(lo), float(hi))
    s.setSingleStep(step if step else max(10 ** -decimals, abs(float(value)) / 10 or 0.1))
    s.setValue(float(value))
    if slot:
        s.valueChanged.connect(lambda *_: slot())
    return s


def set_combo(combo, value):
    i = combo.findData(value)
    if i >= 0:
        combo.setCurrentIndex(i)


class TableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = None

    def set_table(self, table):
        self.beginResetModel()
        self.table = table
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() or self.table is None else len(self.table.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() or self.table is None else len(self.table.cols)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self.table is None:
            return None
        v = self.table.rows[index.row()].get(self.table.cols[index.column()])
        if role == Qt.DisplayRole:
            return fmt(v)
        if role == Qt.TextAlignmentRole:
            return int((Qt.AlignLeft if isinstance(v, str) else Qt.AlignRight) | Qt.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or self.table is None:
            return None
        if orientation == Qt.Horizontal:
            return self.table.cols[section] if section < len(self.table.cols) else None
        return str(section + 1)
