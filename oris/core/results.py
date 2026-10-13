"""Results tables."""
from __future__ import annotations

import csv


def fmt(v):
    """Format a value for display."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v:
            return "NaN"
        if v == int(v) and abs(v) < 1e9:
            return str(int(v))
        if abs(v) < 1e-3 or abs(v) >= 1e7:
            return f"{v:.4g}"
        return f"{v:.3f}"
    return str(v)


def _raw(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return repr(round(v, 6))
    return str(v)


class ResultsTable:
    def __init__(self):
        self.rows = []
        self.cols = []

    def __len__(self):
        return len(self.rows)

    def add(self, row):
        for k in row:
            if k not in self.cols:
                self.cols.append(k)
        self.rows.append(row)

    def extend(self, rows):
        for r in rows:
            self.add(r)

    def clear(self):
        self.rows, self.cols = [], []

    def column(self, name):
        return [r.get(name) for r in self.rows]

    def to_csv(self, path):
        # utf-8-sig so that Excel opens CJK text correctly
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(self.cols)
            for r in self.rows:
                w.writerow([_raw(r.get(c)) for c in self.cols])

    def to_tsv(self):
        lines = ["\t".join(self.cols)]
        lines += ["\t".join(_raw(r.get(c)) for c in self.cols) for r in self.rows]
        return "\n".join(lines)
