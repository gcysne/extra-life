"""Scan a save folder: relative path -> (sha256, size, mtime_ns), with a hash cache keyed by size and mtime."""

import hashlib
import os
import re
from dataclasses import dataclass
from functools import lru_cache

from .util import read_json, write_json


@dataclass(frozen=True)
class FileInfo:
    sha256: str
    size: int
    mtime_ns: int


@lru_cache(maxsize=512)
def _glob_re(pattern):
    """gitignore-like globs: `*` stays in one folder, `**` crosses folders, no `/` = match the name anywhere,
    a trailing `/` matches everything under that folder."""
    if pattern.endswith("/"):
        pattern += "**"
    anchored = "/" in pattern
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        else:
            c = pattern[i]
            out += "[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c)
            i += 1
    if not anchored:
        out = "(?:.*/)?" + out
    return re.compile(out + r"\Z", re.IGNORECASE)


def matches(rel, patterns):
    return any(_glob_re(p).match(rel) for p in patterns)


def wanted(rel, include, exclude):
    return matches(rel, include) and not matches(rel, exclude)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(root, include, exclude, cache_file=None):
    cache = (read_json(cache_file, {}) if cache_file else {}) or {}
    new_cache, out = {}, {}
    root = str(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if not wanted(rel, include, exclude):
                continue
            try:
                st = os.stat(full, follow_symlinks=False)
            except OSError:
                continue
            if not os.path.isfile(full) or os.path.islink(full):
                continue
            c = cache.get(rel)
            if c and c[0] == st.st_size and c[1] == st.st_mtime_ns:
                digest = c[2]
            else:
                try:
                    digest = sha256_file(full)
                except OSError:
                    continue
            new_cache[rel] = [st.st_size, st.st_mtime_ns, digest]
            out[rel] = FileInfo(digest, st.st_size, st.st_mtime_ns)
    if cache_file and new_cache != cache:
        write_json(cache_file, new_cache)
    return out
