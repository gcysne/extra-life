"""Small helpers: time stamps, atomic JSON files, names."""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc)


def iso(dt=None):
    return (dt or utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp(dt=None):
    """Sortable time stamp used in history snapshot names."""
    return (dt or utcnow()).strftime("%Y%m%dT%H%M%SZ")


def parse_stamp(text):
    """Parse the stamp at the start of a snapshot name; None if it has none."""
    try:
        return datetime.strptime(text[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_iso(text):
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "device"


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError):
        return default
    except ValueError:
        return default


def write_json(path, data):
    write_text_atomic(path, json.dumps(data, indent=1, sort_keys=True) + "\n")


def write_text_atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def version_key(text):
    """Sort key for versions like 1.2.3, v1.2.3, 0.1.0-alpha, 0.1.0-alpha.2 (semver order: a release sorts after
    its pre-releases; numeric pre-release parts compare as numbers)."""
    text = str(text or "").strip().lstrip("vV")
    main, _, pre = text.partition("-")
    nums = []
    for part in main.split("."):
        m = re.match(r"\d+", part)
        nums.append(int(m.group()) if m else 0)
    nums = (nums + [0, 0, 0])[:3]
    if not pre:
        return (*nums, 1, ())
    ids = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split("."))
    return (*nums, 0, ids)


def is_newer(candidate, current):
    return version_key(candidate) > version_key(current)
