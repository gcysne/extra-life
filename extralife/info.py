"""Read-only views for the CLI and the plugin: status, providers, recent saves, conflicts, progress."""

import json
from datetime import datetime, timezone

from . import __version__, profiles as profiles_mod, progress as progress_mod, providers as providers_mod
from .engine import Engine
from .util import read_json


def _names(ctx):
    return {p.id: p.name for p in profiles_mod.load_profiles(ctx.paths).values()}


def status(ctx):
    provs = providers_mod.describe_all(ctx)
    connected = [p for p in provs if p["connected"]]
    out = {"version": __version__, "configured": ctx.configured,
           "device": {"id": ctx.device.id, "name": ctx.device.name},
           "running": Engine.is_running(ctx.paths),
           "settings": dict(ctx.cfg["sync"]),
           "providers": connected,
           "remote": ", ".join(p["name"] for p in connected)}
    last = read_json(ctx.paths.last_run_file)
    if last and "providers" in last:
        out["last_run"] = {k: last.get(k) for k in ("mode", "started", "finished", "ok", "summary", "errors",
                                                     "warnings", "skipped")}
    elif last:                                    # written by 0.1.0-alpha (single remote)
        out["last_run"] = {k: last.get(k) for k in ("mode", "started", "finished", "ok", "summary", "errors",
                                                     "warnings")}
        out["last_run"]["skipped"] = [{"key": s["key"], "reason": s["skipped"]}
                                      for s in last.get("sets", []) if s.get("skipped")]
    if out["running"]:
        out["progress"] = progress_mod.read(ctx.paths.progress_file)
    out["conflicts"] = conflicts(ctx)
    out["sets"] = [{"key": s.key, "name": s.profile_name, "root": str(s.root)} for s in profiles_mod.resolve(ctx)]
    return out


def conflicts(ctx):
    names = _names(ctx)
    out = []
    for p in providers_mod.connected(ctx):
        data = read_json(ctx.paths.for_provider(p.id).conflicts_file, {}) or {}
        for key, files in data.items():
            for rel, c in files.items():
                out.append({"provider": p.id, "provider_name": p.name, "key": key,
                            "name": names.get(key.split("/")[0], key), "rel": rel, **c})
    return sorted(out, key=lambda c: (c["key"], c["rel"], c["provider"]))


def recent(ctx, limit=50):
    """Latest version of every synced file, newest first (from every device and provider, as of this device's last
    sync with each)."""
    names = _names(ctx)
    best = {}
    for p in providers_mod.connected(ctx):
        base_dir = ctx.paths.for_provider(p.id).base_dir
        if not base_dir.is_dir():
            continue
        for f in base_dir.glob("*.json"):
            data = read_json(f, {}) or {}
            key = data.get("set", "")
            for rel, e in (data.get("files") or {}).items():
                mt = e.get("mtime_ns") or 0
                row = best.get((key, rel))
                if row and row["_mt"] > mt:
                    continue
                if row and row["_mt"] == mt and row["_sha"] == e.get("sha256"):
                    row["providers"].append(p.name)       # the same version is in several providers
                    continue
                best[(key, rel)] = {"key": key, "name": names.get(key.split("/")[0], key), "rel": rel,
                                    "size": e.get("size"), "device": e.get("device", ""), "synced": e.get("time", ""),
                                    "providers": [p.name], "_mt": mt, "_sha": e.get("sha256"),
                                    "modified": datetime.fromtimestamp(mt / 1e9, timezone.utc).strftime(
                                        "%Y-%m-%dT%H:%M:%SZ") if mt else ""}
    out = sorted(best.values(), key=lambda x: x["modified"], reverse=True)[:limit]
    for r in out:
        r.pop("_mt")
        r.pop("_sha")
    return out


def activity(ctx, limit=50):
    """This device's own sync log (uploads, downloads, conflicts...), newest first."""
    lines = []
    try:
        lines = ctx.paths.events_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        pass
    names = {p["id"]: p["name"] for p in providers_mod.CATALOG}
    out = []
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("provider"):
            e["provider_name"] = names.get(e["provider"], e["provider"])
        out.append(e)
        if len(out) >= limit:
            break
    return out
