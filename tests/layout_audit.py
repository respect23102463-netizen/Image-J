"""Layout audit: fails when any panel overflows or any label/button text is clipped, in every language and at
several window sizes (down to 900 x 640 with the narrowest analysis panel).
Run: QT_QPA_PLATFORM=offscreen python tests/layout_audit.py [screenshot_dir]"""
import os, sys, warnings, tempfile, collections
os.environ["QT_QPA_PLATFORM"] = "offscreen"; warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QApplication, QAbstractButton, QLabel, QComboBox, QCheckBox, QToolButton, QLineEdit,
                               QAbstractSpinBox, QWidget, QScrollArea)
from oris.ui import main as M
from oris.core.roi import Roi
from oris.i18n import T
out = sys.argv[1] if len(sys.argv) > 1 else None
QSettings.setDefaultFormat(QSettings.IniFormat)
app = QApplication([])
w = M.MainWindow(); w.show()
w.open_sample("fluorescence")
for p in [p for _, p in w.panels]:
    for b in p.findChildren(QToolButton):
        if b.property("role") == "disclosure": b.setChecked(True)
issues = collections.Counter(); examples = {}

def text_of(wd):
    if isinstance(wd, QComboBox): return wd.currentText()
    if isinstance(wd, (QAbstractButton, QLabel)): return wd.text()
    return ""

def audit(tag):
    for sa in w.findChildren(QScrollArea):
        if sa.isVisible() and sa.widget() is not None:
            need = sa.widget().minimumSizeHint().width()
            if need > sa.viewport().width() + 1:
                key = (tag.split('|')[0], "PANEL-OVERFLOW", type(sa.widget().parent().parent()).__name__ if sa.widget().parent() else "?")
                issues[key] += 1; examples[key] = f"{tag} need {need} have {sa.viewport().width()}"
    for wd in w.findChildren(QWidget):
        if not wd.isVisible() or wd.width() <= 0: continue
        if isinstance(wd, QLabel) and wd.wordWrap(): 
            if wd.heightForWidth(wd.width()) > wd.height() + 2:
                key = (tag.split('|')[0], type(wd).__name__, wd.text()[:40]); issues[key]+=1; examples[key]=tag
            continue
        if isinstance(wd, (QAbstractButton, QLabel, QComboBox)):
            t = text_of(wd)
            if not t or t.startswith("<"): continue
            need = wd.minimumSizeHint().width() if isinstance(wd, QComboBox) else wd.sizeHint().width()
            if need > wd.width() + 2:
                key = (tag.split('|')[0], type(wd).__name__, t[:40]); issues[key]+=1; examples[key]=f"{tag} need {need} have {wd.width()}"

for code, _ in T.available():
    w.set_language(code)
    for size in ((1280, 760), (1440, 860), (1100, 700), (900, 640)):
        w.resize(*size); w.resizeDocks([w.side_dock], [340], M.Qt.Horizontal); app.processEvents()
        for i in range(w.side_tabs.count()):
            w.side_tabs.setCurrentIndex(i); app.processEvents()
            audit(f"{code}|{size[0]}x{size[1]}|tab{i}")
            if out and size == (1280, 760) and code in ("zh-TW", "ja", "de", "fr"):
                w.grab().save(f"{out}/{code}_tab{i}.png")
w.set_language("en")
for k, n in sorted(issues.items(), key=lambda x: (x[0][0], x[0][1])):
    print(k[0], k[1], repr(k[2]), "x", n, "|", examples[k])
for v in w.views(): v.doc.modified = False
print("layout issues:", len(issues))
sys.exit(1 if issues else 0)
