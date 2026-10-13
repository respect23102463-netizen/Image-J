"""Verify that every translation key used by the program exists in every language,
and that placeholders match the English text. Run: python tests/check_locales.py"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from oris.core.engine import OPS, Engine  # noqa: E402
from oris.core.image import LUT_NAMES  # noqa: E402
from oris.core.samples import SAMPLES  # noqa: E402


def used_keys():
    keys = set()
    pat = re.compile(r'''(?:\btr|self\.T|self\.label|self\.button|self\.group|form_row|OpError|\bA)\((?:[^"']*?,\s*)?["']([a-z_]+\.[A-Za-z0-9_.]+)["']''')
    for base, _, files in os.walk(os.path.join(ROOT, "oris")):
        for f in files:
            if f.endswith(".py"):
                src = open(os.path.join(base, f), encoding="utf-8").read()
                keys.update(pat.findall(src))
                keys.update(re.findall(r'''["']((?:err|tip|gel|cells|fluor|coloc|wound|roi|results|rec|bc|thr)\.[a-z_0-9]+)["']''', src))
    keys = {k for k in keys if not k.endswith(".") and not k.endswith((".py", ".json", ".csv", ".tif", ".png"))}
    for name, op in OPS.items():
        keys.add("op." + name)
        for p in op.params:
            if p["type"] == "raw":
                continue
            keys.add("param." + p["name"])
            if p["choices"] and name != "set_lut":
                keys.update("choice." + c for c in p["choices"])
    keys.update("table." + k for k in Engine.TABLES)
    keys.update("lut." + n for n in LUT_NAMES)
    keys.update("sample." + n for n in SAMPLES)
    for t in ("rect", "ellipse", "polygon", "freehand", "line", "point", "wand", "hand", "zoom"):
        keys.update({"tool." + t, "tooltip." + t})
    keys.update("kind." + k for k in ("rect", "ellipse", "polygon", "freehand", "line", "point"))
    keys.update("panel." + k for k in ("roi", "gel", "cells", "fluor", "wound", "results", "recorder"))
    keys.update({"theme.dark", "theme.light", "help.html", "choice.none", "choice.manual"})
    for pre, vals in (("choice.bands_", ("auto", "dark", "light")), ("choice.bg_", ("auto", "roi", "value")),
                      ("choice.thr_", ("costes", "otsu", "manual", "none"))):
        keys.update(pre + v for v in vals)
    return keys


def main():
    loc = os.path.join(ROOT, "oris", "locales")
    langs = {f[:-5]: json.load(open(os.path.join(loc, f), encoding="utf-8")) for f in sorted(os.listdir(loc))
             if f.endswith(".json")}
    en = langs["en"]
    need = used_keys()
    ok = True
    missing_en = sorted(need - set(en))
    if missing_en:
        ok = False
        print("en: missing", len(missing_en), missing_en)
    unused = sorted(set(en) - need - {"_name"})
    if unused:
        print("en: unused keys", unused)
    ph = re.compile(r"\{(\w*)\}")
    for code, data in langs.items():
        miss = sorted(set(en) - set(data))
        extra = sorted(set(data) - set(en))
        bad = sorted(k for k in en if k in data and sorted(ph.findall(en[k])) != sorted(ph.findall(data[k])))
        empty = sorted(k for k, v in data.items() if not str(v).strip())
        if miss or extra or bad or empty:
            ok = False
        print(f"{code}: {len(data)} keys  missing={miss}  extra={extra}  placeholder-mismatch={bad}  empty={empty}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
