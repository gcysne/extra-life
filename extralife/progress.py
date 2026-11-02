"""Live progress of a sync, written to progress.json for the plugin (status bar icon and panel).

The percentage covers all providers of the run, each an equal share. Inside one provider: connecting and reading
the remote's manifests, then comparing every save folder, then the transfers, weighted by bytes plus a fixed cost
per file (on cloud providers the per-file round trips cost more than the bytes of a small save).
"""

import os
import threading
import time

from .util import iso, read_json, write_json

FILE_COST = 256 * 1024          # bytes-equivalent of one file operation
CONNECTED, COMPARED = 0.08, 0.25  # share of a provider's work done after connecting / after comparing
MIN_WRITE_INTERVAL = 0.3


class Progress:
    def __init__(self, path, mode, total_providers):
        self.path = path
        self.n = max(1, total_providers)
        self.i = 0
        self.frac = 0.0
        self.percent = 0.0
        self.last_write = 0.0
        self.pending = None             # a write skipped by the rate limit is done a moment later, never dropped
        self.lock = threading.RLock()
        self.state = {"running": True, "pid": os.getpid(), "mode": mode, "started": iso(), "percent": 0,
                      "provider": "", "provider_name": "", "provider_index": 0, "providers": self.n,
                      "phase": "starting", "detail": ""}
        self._write(force=True)

    def _write(self, force=False):
        now = time.monotonic()
        if not force and now - self.last_write < MIN_WRITE_INTERVAL:
            if self.pending is None:
                self.pending = threading.Timer(MIN_WRITE_INTERVAL, self._flush)
                self.pending.daemon = True
                self.pending.start()
            return
        if self.pending is not None:
            self.pending.cancel()
            self.pending = None
        self.last_write = now
        self.state["updated"] = iso()
        try:
            write_json(self.path, self.state)
        except OSError:
            pass

    def _set(self, frac, force=False, **fields):
        with self.lock:
            self.frac = min(1.0, max(self.frac, frac))
            # Never move backwards (a provider can get a second pass when another one brought new saves).
            self.percent = max(self.percent, min(99.0, (self.i + self.frac) / self.n * 100))
            self.state.update(fields, percent=round(self.percent, 1))
            self._write(force)

    def _flush(self):
        with self.lock:
            self.pending = None
            self._write(force=True)

    def provider(self, index, pid, name):
        with self.lock:
            self.i, self.frac = min(index, self.n - 1), 0.0
        self._set(0.0, force=True, provider=pid, provider_name=name, provider_index=index, phase="connecting",
                  detail="")

    def connecting(self, step, steps):
        """Steps inside connecting (reach the folder, check the format, take the lock, read the manifests)."""
        self._set(CONNECTED * step / max(1, steps), force=True, phase="connecting")

    def connected(self):
        self._set(CONNECTED, force=True, phase="comparing", detail="")

    def comparing(self, done, total, name=""):
        self._set(CONNECTED + (COMPARED - CONNECTED) * done / max(1, total), phase="comparing", detail=name)

    def transfer(self, done, total, name=""):
        frac = 1.0 if total <= 0 else COMPARED + (1 - COMPARED) * min(1.0, done / total)
        self._set(frac, phase="transferring" if frac < 1 else "finishing", detail=name)

    def finish(self, ok):
        with self.lock:
            self.state.update(running=False, percent=100, phase="done", ok=bool(ok), finished=iso(), detail="")
            self._write(force=True)


class NullProgress:
    def provider(self, *a): pass
    def connecting(self, *a): pass
    def connected(self): pass
    def comparing(self, *a): pass
    def transfer(self, *a): pass
    def finish(self, *a): pass


def read(path):
    """progress.json, with running=False if the process that wrote it is gone (crash, kill)."""
    p = read_json(path, {}) or {}
    if p.get("running"):
        try:
            pid = int(p.get("pid", 0))
            if pid <= 0:
                raise ValueError(pid)
            os.kill(pid, 0)
        except (OSError, ValueError):
            p["running"] = False
            p["phase"] = "interrupted"
    return p
