"""Block RMS analysis with an indexed disk representation of voiced intervals."""
from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import numpy as np
import soundfile as sf


def rolling_mask(read_mono, total, start, count, window, threshold):
    left, right = window // 2, (window - 1) // 2
    lo, hi = max(0, start - left), min(total, start + count + right)
    mono = np.asarray(read_mono(lo, hi - lo), dtype=np.float32)
    square = (mono * mono).astype(np.float64)
    padded = np.pad(square, (max(0, left - start), max(0, start + count + right - total)))
    sums = np.concatenate(([0.0], np.cumsum(padded, dtype=np.float64)))
    energy = (sums[window:] - sums[:-window]) / window
    return energy[:count] > threshold ** 2


class EnergyIndex:
    def __init__(self, db, total):
        self.db, self.total = db, total

    @classmethod
    def build(cls, read_mono, total, sr, threshold, win_sec, block_frames=65536, path: Path | None = None):
        if path and path.is_file():
            try:
                db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                stored = db.execute("SELECT value FROM metadata WHERE name='frames'").fetchone()
                parameters = db.execute("SELECT value FROM metadata WHERE name='parameters'").fetchone()
                if stored and int(stored[0]) == total and parameters and parameters[0] == repr((sr, threshold, win_sec)):
                    return cls(db, total)
                db.close()
            except sqlite3.Error:
                pass
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp") if path else None
        if tmp:
            tmp.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(tmp) if tmp else ":memory:")
        db.execute("PRAGMA cache_size=-8192")
        db.execute("CREATE TABLE IF NOT EXISTS runs (lo INTEGER PRIMARY KEY, hi INTEGER NOT NULL)")
        db.execute("CREATE INDEX IF NOT EXISTS run_end ON runs(hi)")
        db.execute("CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT)")
        pending = None
        window = max(1, int(sr * win_sec))
        for start in range(0, total, block_frames):
            count = min(block_frames, total - start)
            mask = rolling_mask(read_mono, total, start, count, window, threshold)
            edges = np.flatnonzero(np.diff(np.concatenate(([False], mask, [False])).astype(np.int8)))
            local = list(zip(edges[::2], edges[1::2]))
            if pending is not None and (not local or local[0][0] != 0):
                db.execute("INSERT OR REPLACE INTO runs VALUES (?,?)", (pending, start))
                pending = None
            for lo, hi in local:
                first = pending if pending is not None and lo == 0 else start + int(lo)
                pending = first if hi == count else None
                if hi != count:
                    db.execute("INSERT OR REPLACE INTO runs VALUES (?,?)", (first, start + int(hi)))
        if pending is not None:
            db.execute("INSERT OR REPLACE INTO runs VALUES (?,?)", (pending, total))
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('frames',?)", (str(total),))
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('parameters',?)", (repr((sr, threshold, win_sec)),))
        db.commit()
        if path:
            db.close()
            os.replace(tmp, path)
            db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        return cls(db, total)

    def count(self, lo, hi):
        if hi <= lo:
            return 0
        previous = self.db.execute("SELECT lo FROM runs WHERE lo<=? ORDER BY lo DESC LIMIT 1", (lo,)).fetchone()
        lower = previous[0] if previous else lo
        value = self.db.execute("SELECT SUM(MIN(hi,?) - MAX(lo,?)) FROM runs WHERE lo>=? AND lo<? AND hi>?", (hi, lo, lower, hi, lo)).fetchone()[0]
        return int(value or 0)

    def bounds(self, lo, hi):
        previous = self.db.execute("SELECT lo FROM runs WHERE lo<=? ORDER BY lo DESC LIMIT 1", (lo,)).fetchone()
        lower = previous[0] if previous else lo
        first, last = self.db.execute("SELECT MIN(lo),MAX(hi) FROM runs WHERE lo>=? AND lo<? AND hi>?", (lower, hi, lo)).fetchone()
        return None if first is None else (max(lo, first), min(hi, last))

    def runs(self):
        yield from self.db.execute("SELECT lo,hi FROM runs ORDER BY lo")

    def close(self):
        self.db.close()
