"""extralife command line. Every command that the Decky plugin uses supports --json."""

import argparse
import json
import subprocess
import sys

from . import __version__, config as config_mod, info, profiles as profiles_mod
from .backends import BackendError, make_backend
from .context import Context
from .engine import Busy, Engine, EngineError
from .util import human_size


def _out(args, data, text_fn):
    if getattr(args, "json", False):
        print(json.dumps(data, indent=1, sort_keys=True))
    else:
        text_fn(data)


def _print_report(r):
    if r.get("dry_run"):
        print("Dry run: nothing was changed.")
    for s in r["sets"]:
        parts = [f"{len(s[k])} {label}" for k, label in (
            ("uploaded", "up"), ("downloaded", "down"), ("remote_deleted", "deleted in cloud"),
            ("local_deleted", "deleted here"), ("conflicts", "conflict(s)")) if s.get(k)]
        if s.get("skipped"):
            parts.append(f"skipped: {s['skipped']}")
        if s.get("error"):
            parts.append(f"error: {s['error']}")
        if parts:
            print(f"  {s['key']}: {', '.join(parts)}")
            for k in ("uploaded", "downloaded", "remote_deleted", "local_deleted", "conflicts"):
                for f in s.get(k, [])[:20]:
                    print(f"      {k:<14} {f}")
    for w in r.get("warnings", []):
        print(f"warning: {w}")
    for e in r["errors"]:
        print(f"error: {e}")
    sm = r.get("summary") or {}
    if r["ok"] and not r.get("dry_run"):
        print(f"Done: {sm.get('uploaded', 0)} up, {sm.get('downloaded', 0)} down, "
              f"{sm.get('conflicts', 0)} conflict(s)." if any(sm.values()) else "Everything in sync.")


def _run(ctx, args, mode, **kw):
    if not ctx.configured:
        msg = "Extra Life isn't set up yet: run `extralife setup`."
        if args.json:
            print(json.dumps({"ok": False, "errors": [msg], "not_configured": True}))
        elif not getattr(args, "quiet", False):
            print(msg)
        return 0 if mode == "sync" else 1
    try:
        r = Engine(ctx).run(mode, only_profiles=args.profile or None, dry_run=getattr(args, "dry_run", False),
                            lock_wait=getattr(args, "lock_wait", 0), **kw)
    except Busy as e:
        r = {"ok": False, "errors": [str(e)], "busy": True, "sets": []}
    if args.json:
        print(json.dumps(r, indent=1, sort_keys=True))
    elif not (getattr(args, "quiet", False) and r["ok"]):
        _print_report(r)
    return 0 if r["ok"] else 1


def cmd_sync(ctx, args):
    wait = args.wait if args.wait is not None else ctx.cfg["sync"].get("wait_for_exit", 60)
    return _run(ctx, args, "sync", wait=wait)


def cmd_push(ctx, args):
    return _run(ctx, args, "push", only_set=args.set, only_rels=args.file or None)


def cmd_pull(ctx, args):
    return _run(ctx, args, "pull", only_set=args.set, only_rels=args.file or None)


def cmd_status(ctx, args):
    def text(s):
        print(f"Extra Life {s['version']} on {s['device']['name']}")
        if not s["configured"]:
            print("Not set up: run `extralife setup`.")
            return
        print(f"Remote: {s['remote'] or s.get('remote_error')}")
        lr = s.get("last_run")
        if lr:
            state = "ok" if lr["ok"] else "FAILED"
            print(f"Last {lr['mode']}: {lr['finished']} ({state})")
            for e in lr.get("errors") or []:
                print(f"  error: {e}")
            for sk in lr.get("skipped") or []:
                print(f"  skipped {sk['key']}: {sk['reason']}")
        else:
            print("Never synced.")
        if s["running"]:
            print("A sync is running now.")
        print(f"Save folders: {len(s['sets'])}; conflicts: {len(s['conflicts'])}")
    _out(args, info.status(ctx), text)
    return 0


def cmd_recent(ctx, args):
    def text(rows):
        if not rows:
            print("Nothing synced yet.")
        for r in rows:
            print(f"{r['modified']}  {r['name']:<22} {human_size(r['size']):>9}  {r['device']:<14} {r['rel']}")
    _out(args, info.recent(ctx, args.limit), text)
    return 0


def cmd_log(ctx, args):
    def text(rows):
        for e in rows:
            print(f"{e['time']}  {e['action']:<13} {e['key']:<22} {e['rel']}")
    _out(args, info.activity(ctx, args.limit), text)
    return 0


def cmd_conflicts(ctx, args):
    def text(rows):
        if not rows:
            print("No conflicts.")
        for c in rows:
            other = (c.get("remote") or {}).get("device", "?")
            print(f"{c['key']}  {c['rel']}  (changed here and on {other})")
        if rows:
            print("Resolve: extralife resolve --keep local|cloud [--set KEY --file PATH | --all]")
    _out(args, info.conflicts(ctx), text)
    return 0


def cmd_resolve(ctx, args):
    rows = info.conflicts(ctx)
    if not args.all:
        if not (args.set and args.file):
            print("give --set and --file, or --all", file=sys.stderr)
            return 2
        rows = [c for c in rows if c["key"] == args.set and c["rel"] == args.file]
        if not rows:
            print("no such conflict", file=sys.stderr)
            return 1
    mode = "push" if args.keep == "local" else "pull"
    reports, ok = [], True
    for key in sorted({c["key"] for c in rows}):
        rels = [c["rel"] for c in rows if c["key"] == key]
        try:
            r = Engine(ctx).run(mode, only_set=key, only_rels=rels)
        except Busy as e:
            r = {"ok": False, "errors": [str(e)], "sets": []}
        reports.append(r)
        ok = ok and r["ok"]
    if args.json:
        print(json.dumps({"ok": ok, "reports": reports}, indent=1))
    else:
        for r in reports:
            _print_report(r)
        if not reports:
            print("No conflicts.")
    return 0 if ok else 1


def cmd_history(ctx, args):
    try:
        rows = Engine(ctx).history(args.limit)
    except BackendError as e:
        print(json.dumps({"error": str(e)}) if args.json else f"error: {e}")
        return 1

    def text(rows):
        if not rows:
            print("No older versions stored yet.")
        for h in rows:
            print(f"{h['id']}  ({len(h['files'])} file(s))")
            for f in h["files"][:10]:
                print(f"    {f['key']}  {f['rel']}  {human_size(f['size'])}")
    _out(args, rows, text)
    return 0


def cmd_restore(ctx, args):
    try:
        r = Engine(ctx).restore(args.snapshot, args.set, args.file)
    except (EngineError, BackendError, Busy) as e:
        r = {"ok": False, "errors": [str(e)], "sets": []}
    if args.json:
        print(json.dumps(r, indent=1))
    else:
        _print_report(r)
    return 0 if r["ok"] else 1


def cmd_profiles(ctx, args):
    errors = []
    rows = profiles_mod.describe_all(ctx, errors)

    def text(rows):
        for p in rows:
            mark = "on " if p["enabled"] else "off"
            where = next((s["root"] for s in p["sets"] if s["root"] and s["kind"] == "saves"), "not found")
            print(f"[{mark}] {p['id']:<12} {p['name']:<28} {where}")
        for e in errors:
            print(f"warning: {e}")
    _out(args, rows, text)
    return 0


def cmd_profile(ctx, args):
    p = ctx.cfg["profiles"]
    enabled, disabled = list(p.get("enabled") or []), list(p.get("disabled") or [])
    known = profiles_mod.load_profiles(ctx.paths)
    if args.id not in known:
        print(f"unknown profile: {args.id}", file=sys.stderr)
        return 1
    enabled = [x for x in enabled if x != args.id]
    disabled = [x for x in disabled if x != args.id]
    if args.action == "enable":
        enabled.append(args.id)
    elif args.action == "disable":
        disabled.append(args.id)
    p["enabled"], p["disabled"] = enabled, disabled
    config_mod.save(ctx.paths.config_file, ctx.cfg)
    if args.json:
        print(json.dumps({"ok": True}))
    return 0


def cmd_config(ctx, args):
    if args.action == "get":
        if args.key:
            v = config_mod.get_key(ctx.cfg, args.key)
            print(json.dumps(v) if args.json else v)
        else:
            print(json.dumps(ctx.cfg, indent=1) if args.json else config_mod.dumps(ctx.cfg), end="")
        return 0
    if args.action == "set":
        if args.value is None:
            print("config set KEY VALUE", file=sys.stderr)
            return 2
        config_mod.set_key(ctx.cfg, args.key, config_mod.parse_value(args.value))
        config_mod.save(ctx.paths.config_file, ctx.cfg)
        if args.json:
            print(json.dumps({"ok": True}))
        return 0
    print(ctx.paths.config_file)
    return 0


def cmd_init(ctx, args):
    r = ctx.cfg["remote"]
    r["type"] = args.type
    if args.type == "local":
        r["path"] = args.path or ""
    elif args.type == "rsync-ssh":
        r["host"], r["path"] = args.host or "", args.path or ""
    elif args.type == "rclone":
        r["remote"] = args.remote or ""
    if args.device_name:
        ctx.cfg["device_name"] = args.device_name
    make_backend(ctx.cfg)                     # validates the settings
    config_mod.save(ctx.paths.config_file, ctx.cfg)
    print(f"Saved {ctx.paths.config_file}")
    return cmd_doctor(Context.load(ctx.paths), args)


def _ask(prompt, default=""):
    v = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return v or default


def cmd_setup(ctx, args):
    print("Extra Life setup. Where should save games go?")
    print("  1) A folder: SD card, USB drive or a mounted network share")
    print("  2) A cloud service through rclone (Google Drive, Dropbox, OneDrive, S3, WebDAV...)")
    print("  3) Another computer or NAS over SSH (rsync)")
    choice = _ask("Choose 1-3", "1")
    r = ctx.cfg["remote"]
    if choice == "2":
        from .backends.rclone import find_rclone
        if not find_rclone(r.get("rclone", "")):
            if _ask("rclone isn't installed. Download the official build now? (y/n)", "y").lower().startswith("y"):
                from .rclone_install import install
                install()
            else:
                return 1
        from .backends.rclone import find_rclone as again
        rc = again(r.get("rclone", ""))
        remotes = subprocess.run([rc, "listremotes"], capture_output=True, text=True).stdout.split()
        if not remotes:
            print("No rclone remotes yet. Starting `rclone config`: choose n (new remote), give it a name (e.g."
                  " gdrive), pick your provider and sign in in the browser that opens.")
            subprocess.run([rc, "config"])
            remotes = subprocess.run([rc, "listremotes"], capture_output=True, text=True).stdout.split()
        if not remotes:
            print("Still no rclone remote; run setup again when you have one.")
            return 1
        print("rclone remotes: " + " ".join(remotes))
        name = _ask("Remote to use", remotes[0]).rstrip(":")
        folder = _ask("Folder for Extra Life in it (everything goes inside)", "ExtraLife").strip("/") or "ExtraLife"
        r.update(type="rclone", remote=f"{name}:{folder}")
    elif choice == "3":
        r.update(type="rsync-ssh", host=_ask("SSH host (as in `ssh HOST`)"), path=_ask("Folder on the host"))
    else:
        r.update(type="local", path=_ask("Folder", r.get("path") or ""))
    ctx.cfg["device_name"] = _ask("Name for this device", ctx.device.name)
    try:
        make_backend(ctx.cfg)
    except BackendError as e:
        print(f"error: {e}")
        return 1
    config_mod.save(ctx.paths.config_file, ctx.cfg)
    print(f"Saved {ctx.paths.config_file}")
    return cmd_doctor(Context.load(ctx.paths), args)


def cmd_doctor(ctx, args):
    ok = True
    print(f"Extra Life {__version__}; device {ctx.device.name} ({ctx.device.id})")
    print(f"Config: {ctx.paths.config_file}{'' if ctx.configured else ' (not set up)'}")
    try:
        b = make_backend(ctx.cfg)
        b.check()
        print(f"Remote: {b.describe()}: reachable")
    except BackendError as e:
        ok = False
        print(f"Remote: PROBLEM: {e}")
    errors = []
    sets = profiles_mod.resolve(ctx, errors)
    print(f"Save folders to sync: {len(sets)}")
    for s in sets:
        print(f"  {s.key:<24} {s.root}")
    for e in errors:
        print(f"  warning: {e}")
    print("Not syncing save states (sync.include_states = false)." if not ctx.cfg["sync"]["include_states"]
          else "Save states are synced too.")
    return 0 if ok else 1


def cmd_prune(ctx, args):
    removed = Engine(ctx, make_backend(ctx.cfg)).prune()
    print(f"Removed {len(removed)} old version folder(s).")
    return 0


def cmd_install_rclone(ctx, args):
    from .rclone_install import install
    install()
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="extralife", description="Keep emulator save games in sync.")
    ap.add_argument("--version", action="version", version=f"Extra Life {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help, json_flag=True):
        p = sub.add_parser(name, help=help, description=help)
        p.set_defaults(fn=fn)
        if json_flag:
            p.add_argument("--json", action="store_true", help="machine-readable output")
        return p

    p = add("sync", cmd_sync, "sync both ways (what the background service runs)")
    p.add_argument("--profile", action="append", help="only this emulator profile (repeatable)")
    p.add_argument("--dry-run", action="store_true", help="show what would change")
    p.add_argument("--wait", type=int, help="seconds to wait for running emulators to exit")
    p.add_argument("--lock-wait", type=int, default=0, help="seconds to wait if another run is in progress")
    p.add_argument("--quiet", action="store_true", help="print only problems")
    for name, fn, help in (("push", cmd_push, "force: make the cloud match this device"),
                           ("pull", cmd_pull, "force: make this device match the cloud")):
        p = add(name, fn, help)
        p.add_argument("--profile", action="append", help="only this emulator profile (repeatable)")
        p.add_argument("--set", help="only this save folder (profile/set)")
        p.add_argument("--file", action="append", help="only this file in --set (repeatable)")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--lock-wait", type=int, default=30)
    add("status", cmd_status, "show the setup and the last sync")
    p = add("recent", cmd_recent, "latest synced saves, newest first")
    p.add_argument("--limit", type=int, default=30)
    p = add("log", cmd_log, "what this device uploaded, downloaded or flagged")
    p.add_argument("--limit", type=int, default=50)
    add("conflicts", cmd_conflicts, "files changed on two devices")
    p = add("resolve", cmd_resolve, "settle conflicts by keeping one side")
    p.add_argument("--keep", choices=("local", "cloud"), required=True)
    p.add_argument("--set")
    p.add_argument("--file")
    p.add_argument("--all", action="store_true")
    p = add("history", cmd_history, "older versions kept in the cloud")
    p.add_argument("--limit", type=int, default=30)
    p = add("restore", cmd_restore, "bring back an older version and make it the newest")
    p.add_argument("snapshot")
    p.add_argument("set")
    p.add_argument("file")
    add("profiles", cmd_profiles, "emulators Extra Life knows and whether they sync")
    p = add("profile", cmd_profile, "turn an emulator on or off")
    p.add_argument("action", choices=("enable", "disable", "auto"))
    p.add_argument("id")
    p = add("config", cmd_config, "show or change settings (e.g. config set sync.include_states true)")
    p.add_argument("action", choices=("get", "set", "path"))
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p = add("init", cmd_init, "set up the remote without questions", json_flag=False)
    p.add_argument("--type", choices=("local", "rsync-ssh", "rclone"), required=True)
    p.add_argument("--path")
    p.add_argument("--host")
    p.add_argument("--remote")
    p.add_argument("--device-name")
    add("setup", cmd_setup, "set up the remote interactively", json_flag=False)
    add("doctor", cmd_doctor, "check the setup", json_flag=False)
    add("prune", cmd_prune, "delete versions older than sync.history_days now", json_flag=False)
    add("install-rclone", cmd_install_rclone, "download the official rclone build", json_flag=False)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        ctx = Context.load()
        return args.fn(ctx, args)
    except (config_mod.ConfigError, BackendError, EngineError) as e:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "errors": [str(e)]}))
        else:
            print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
