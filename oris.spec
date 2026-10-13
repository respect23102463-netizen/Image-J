# PyInstaller recipe:  pyinstaller --noconfirm oris.spec
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

VERSION = "1.0.0"
datas = [("oris/locales", "oris/locales")] + collect_data_files("skimage")
hidden = collect_submodules("skimage") + ["scipy.special.cython_special"]
excludes = ["matplotlib", "tkinter", "PyQt5", "PyQt6", "IPython", "pytest", "pandas",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
            "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts",
            "PySide6.QtDataVisualization"]

a = Analysis(["run.py"], pathex=["."], datas=datas, hiddenimports=hidden, excludes=excludes)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ORIS", console=False,
          icon="assets/icon.ico" if sys.platform.startswith("win") else None)
coll = COLLECT(exe, a.binaries, a.datas, name="ORIS")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="ORIS.app", icon="assets/icon.icns", bundle_identifier="tw.openresearch.oris",
                 version=VERSION,
                 info_plist={"CFBundleName": "ORIS", "CFBundleDisplayName": "ORIS",
                             "CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
                             "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0",
                             "NSHumanReadableCopyright": "Open Research Technology Co., Ltd.",
                             "CFBundleDocumentTypes": [{"CFBundleTypeName": "Image", "CFBundleTypeRole": "Viewer",
                                                        "LSItemContentTypes": ["public.tiff", "public.png", "public.jpeg",
                                                                               "com.microsoft.bmp"]}]})
