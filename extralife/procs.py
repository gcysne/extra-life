"""Is an emulator running? Profiles list process names (globs, case-insensitive)."""

import fnmatch
import os


def running_names():
    names = set()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/comm", encoding="utf-8", errors="replace") as f:
                names.add(f.read().strip().lower())
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv0 = f.read().split(b"\0", 1)[0].decode("utf-8", "replace")
            if argv0:
                names.add(os.path.basename(argv0).lower())
        except OSError:
            continue
    names.discard("")
    return names


def is_running(patterns, names=None):
    if not patterns:
        return False
    names = running_names() if names is None else names
    pats = [p.lower() for p in patterns]
    return any(fnmatch.fnmatchcase(n, p) for n in names for p in pats)
