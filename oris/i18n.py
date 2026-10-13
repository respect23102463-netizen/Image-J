"""Runtime translation. Each language is one JSON file in ``oris/locales`` (or ``~/.oris/locales``);
adding a language means adding one file - no code changes."""
from __future__ import annotations

import json
from pathlib import Path

LOCALE_DIR = Path(__file__).parent / "locales"
USER_DIR = Path.home() / ".oris" / "locales"
ORDER = ["zh-TW", "en", "ja", "ko", "es", "fr", "de"]


class Translator:
    def __init__(self):
        self.lang = "en"
        self._en = self._load("en")
        self._cur = self._en

    @staticmethod
    def _files():
        files = {}
        for d in (LOCALE_DIR, USER_DIR):
            if d.is_dir():
                for f in sorted(d.glob("*.json")):
                    files[f.stem] = f
        return files

    def _load(self, code):
        f = self._files().get(code)
        if f is None:
            return {}
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def available(self):
        """[(code, native name)] in a stable, friendly order."""
        codes = list(self._files())
        codes.sort(key=lambda c: (ORDER.index(c) if c in ORDER else len(ORDER), c))
        return [(c, self._load(c).get("_name", c)) for c in codes]

    def match(self, system_name):
        """Best language for a system locale name such as 'zh_TW' or 'ja_JP'."""
        codes = [c for c, _ in self.available()]
        want = system_name.replace("_", "-")
        if want in codes:
            return want
        if want.lower().startswith("zh"):
            return "zh-TW" if "zh-TW" in codes else "en"
        base = want.split("-")[0]
        return base if base in codes else "en"

    def set_language(self, code):
        data = self._load(code)
        if data:
            self.lang, self._cur = code, data

    def has(self, key):
        return key in self._cur or key in self._en

    def tr(self, key, **kw):
        s = self._cur.get(key) or self._en.get(key) or key
        if kw:
            try:
                return s.format(**kw)
            except (KeyError, IndexError, ValueError):
                return s
        return s

    def opt(self, key, default):
        """Translation if one exists, otherwise ``default``."""
        return self.tr(key) if self.has(key) else default


T = Translator()
tr = T.tr
