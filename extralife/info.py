"""Read-only views for the CLI and the plugin: status, recent saves, conflicts."""

import json
from datetime import datetime, timezone

from . import __version__, profiles as profiles_mod
from .backends import BackendError, make_backend
from .engine import Engine
from .util import read_json


def _names(ctx):
    return {p.id: p.name for p in profiles_mod.load_profiles(ctx.paths).values()}


def status(ctx):
    out = {"version": __version__, "configured": ctx.configured,
           "device": {"id": ctx.device.id, "name": ctx.device.name},
           "running": Engine.is_running(ctx.paths),
           "settings": dict(ctx.cfg["sync"]), "remote_type": ctx.cfg["remote"].get("type", "")}
    try:
        out["remote"] = make_backend(ctx.cfg).describe() if ctx.configured else ""
    except BackendError as e:
        out["remote"] = ""
        out["remote_error"] = str(e)
    last = read_json(ctx.paths.last_run_file)
    if last:
        out["last_run"] = {k: last.get(k) for k in ("mode", "started", "finished", "ok", "summary", "errors",
                                                     "warnings", "remote")}
        out["last_run"]["skipped"] = [{"key": s["key"], "reason": s["skipped"]}
                                      for s in last.get("sets", []) if s.get("skipped")]
    out["conflicts"] = conflicts(ctx)
    out["sets"] = [{"key": s.key, "name": s.profile_name, "root": str(s.root)} for s in profiles_mod.resolve(ctx)]
    return out


def conflicts(ctx):
    names = _names(ctx)
    out = []
    for key, files in (read_json(ctx.paths.conflicts_file, {}) or {}).items():
        for rel, c in files.items():
            out.append({"key": key, "name": names.get(key.split("/")[0], key), "rel": rel, **c})
    return sorted(out, key=lambda c: (c["key"], c["rel"]))


def recent(ctx, limit=50):
    """Latest version of every synced file, newest first (from every device, as of this device's last sync)."""
    names = _names(ctx)
    out = []
    if ctx.paths.base_dir.is_dir():
        for f in ctx.paths.base_dir.glob("*.json"):
            data = read_json(f, {}) or {}
            key = data.get("set", "")
            for rel, e in (data.get("files") or {}).items():
                mt = e.get("mtime_ns") or 0
                out.append({"key": key, "name": names.get(key.split("/")[0], key), "rel": rel,
                            "size": e.get("size"), "device": e.get("device", ""), "synced": e.get("time", ""),
                            "modified": datetime.fromtimestamp(mt / 1e9, timezone.utc).strftime(
                                "%Y-%m-%dT%H:%M:%SZ") if mt else ""})
    out.sort(key=lambda x: x["modified"], reverse=True)
    return out[:limit]


def activity(ctx, limit=50):
    """This device's own sync log (uploads, downloads, conflicts...), newest first."""
    lines = []
    try:
        lines = ctx.paths.events_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        pass
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out
