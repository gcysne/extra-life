"""extralife command line. Every command that the Decky plugin uses supports --json."""

import argparse
import json
import signal
import sys

from . import __version__, config as config_mod, info, profiles as profiles_mod, progress as progress_mod
from . import providers as providers_mod
from .backends import BackendError
from .context import Context
from .engine import Busy, Engine, EngineError, run_all
from .providers import ProviderError
from .util import human_size


def _out(args, data, text_fn):
    if getattr(args, "json", False):
        print(json.dumps(data, indent=1, sort_keys=True))
    else:
        text_fn(data)


def _print_sets(sets, indent="  "):
    for s in sets:
        parts = [f"{len(s[k])} {label}" for k, label in (
            ("uploaded", "up"), ("downloaded", "down"), ("remote_deleted", "deleted there"),
            ("local_deleted", "deleted here"), ("conflicts", "conflict(s)")) if s.get(k)]
        if s.get("skipped"):
            parts.append(f"skipped: {s['skipped']}")
        if s.get("error"):
            parts.append(f"error: {s['error']}")
        if parts:
            print(f"{indent}{s['key']}: {', '.join(parts)}")
            for k in ("uploaded", "downloaded", "remote_deleted", "local_deleted", "conflicts"):
                for f in s.get(k, [])[:20]:
                    print(f"{indent}    {k:<14} {f}")


def _print_report(r):
    if r.get("dry_run"):
        print("Dry run: nothing was changed.")
    for pr in r.get("providers", []):
        changed = [s for s in pr["sets"] if any(s.get(k) for k in (
            "uploaded", "downloaded", "remote_deleted", "local_deleted", "conflicts", "skipped", "error"))]
        if changed or pr.get("errors"):
            print(f"{pr.get('provider_name') or pr.get('remote')}{' (second pass)' if pr.get('pass') == 2 else ''}:")
            _print_sets(changed)
    if "providers" not in r:
        _print_sets(r.get("sets", []))
    for w in r.get("warnings", []):
        print(f"warning: {w}")
    for e in r["errors"]:
        print(f"error: {e}")
    sm = r.get("summary") or {}
    if r["ok"] and not r.get("dry_run"):
        print(f"Done: {sm.get('uploaded', 0)} up, {sm.get('downloaded', 0)} down, "
              f"{sm.get('conflicts', 0)} conflict(s)." if any(sm.values()) else "Everything in sync.")


def _emit(args, r):
    if args.json:
        print(json.dumps(r, indent=1, sort_keys=True))
    elif not (getattr(args, "quiet", False) and r["ok"]):
        _print_report(r)
    return 0 if r["ok"] else 1


def _run(ctx, args, mode, **kw):
    if not ctx.configured:
        msg = "No storage provider connected: run `extralife setup` or connect one in the Decky plugin."
        if args.json:
            print(json.dumps({"ok": False, "errors": [msg], "not_configured": True}))
        elif not getattr(args, "quiet", False):
            print(msg)
        return 0 if mode == "sync" else 1
    try:
        r = run_all(ctx, mode, providers=args.provider or None, only_profiles=args.profile or None,
                    dry_run=getattr(args, "dry_run", False), lock_wait=getattr(args, "lock_wait", 0), **kw)
    except Busy as e:
        r = {"ok": False, "errors": [str(e)], "busy": True, "providers": []}
    return _emit(args, r)


def cmd_sync(ctx, args):
    wait = args.wait if args.wait is not None else ctx.cfg["sync"].get("wait_for_exit", 60)
    return _run(ctx, args, "sync", wait=wait)


def cmd_push(ctx, args):
    return _run(ctx, args, "push", only_set=args.set, only_rels=args.file or None)


def _one_provider(ctx, args, what):
    """The provider a command acts on: --provider, or the only connected one."""
    if args.provider:
        return providers_mod.get(ctx, args.provider[0] if isinstance(args.provider, list) else args.provider)
    provs = providers_mod.connected(ctx)
    if len(provs) == 1:
        return provs[0]
    if not provs:
        raise ProviderError("no storage provider connected")
    raise ProviderError(f"{what}: choose a provider with --provider ({', '.join(p.id for p in provs)})")


def cmd_pull(ctx, args):
    # Pulling from two providers at once would let the second overwrite the first: always one provider.
    try:
        p = _one_provider(ctx, args, "pull")
    except ProviderError as e:
        return _emit(args, {"ok": False, "errors": [str(e)], "providers": []})
    args.provider = [p.id]
    return _run(ctx, args, "pull", only_set=args.set, only_rels=args.file or None)


def cmd_status(ctx, args):
    def text(s):
        print(f"Extra Life {s['version']} on {s['device']['name']}")
        if not s["configured"]:
            print("No storage provider connected: run `extralife setup`.")
            return
        for p in s["providers"]:
            lr = p.get("last_run") or {}
            state = ("ok" if lr.get("ok") else "FAILED") if lr else "never synced"
            print(f"  {p['name']:<28} {p['target'] or p.get('error', '')}  [{state}]")
        lr = s.get("last_run")
        if lr:
            print(f"Last {lr['mode']}: {lr['finished']} ({'ok' if lr['ok'] else 'FAILED'})")
            for e in lr.get("errors") or []:
                print(f"  error: {e}")
            for sk in lr.get("skipped") or []:
                print(f"  skipped {sk['key']}: {sk['reason']}")
        else:
            print("Never synced.")
        if s["running"]:
            pg = s.get("progress") or {}
            print(f"A sync is running now: {pg.get('percent', 0):.0f}% ({pg.get('provider_name', '')} "
                  f"{pg.get('phase', '')})")
        print(f"Save folders: {len(s['sets'])}; conflicts: {len(s['conflicts'])}")
    _out(args, info.status(ctx), text)
    return 0


def cmd_progress(ctx, args):
    def text(p):
        if not p:
            print("No sync has run yet.")
        else:
            state = "running" if p.get("running") else p.get("phase", "")
            print(f"{p.get('percent', 0):.0f}% {state} {p.get('provider_name', '')} {p.get('detail', '')}".rstrip())
    _out(args, progress_mod.read(ctx.paths.progress_file), text)
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
            print(f"{e['time']}  {e['action']:<13} {e.get('provider', ''):<9} {e['key']:<22} {e['rel']}")
    _out(args, info.activity(ctx, args.limit), text)
    return 0


def cmd_conflicts(ctx, args):
    def text(rows):
        if not rows:
            print("No conflicts.")
        for c in rows:
            other = (c.get("remote") or {}).get("device", "?")
            print(f"{c['provider']:<9} {c['key']}  {c['rel']}  (changed here and on {other})")
        if rows:
            print("Resolve: extralife resolve --keep local|cloud [--provider ID] [--set KEY --file PATH | --all]")
    _out(args, info.conflicts(ctx), text)
    return 0


def cmd_resolve(ctx, args):
    rows = info.conflicts(ctx)
    if args.provider:
        rows = [c for c in rows if c["provider"] == args.provider]
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
    for pid, key in sorted({(c["provider"], c["key"]) for c in rows}):
        rels = [c["rel"] for c in rows if c["key"] == key and c["provider"] == pid]
        try:
            r = Engine(ctx, provider=providers_mod.get(ctx, pid)).run(mode, only_set=key, only_rels=rels)
        except (Busy, ProviderError) as e:
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
        p = _one_provider(ctx, args, "history")
        rows = Engine(ctx, provider=p).history(args.limit)
    except (BackendError, ProviderError) as e:
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
        p = _one_provider(ctx, args, "restore")
        r = Engine(ctx, provider=p).restore(args.snapshot, args.set, args.file, push=False)
        if r["ok"]:      # the restored version becomes the newest everywhere
            r = run_all(ctx, "push", only_set=args.set, only_rels=[args.file], lock_wait=30)
    except (EngineError, BackendError, Busy, ProviderError) as e:
        r = {"ok": False, "errors": [str(e)], "sets": []}
    return _emit(args, r)


# ---------- providers ----------

def cmd_providers(ctx, args):
    rows = providers_mod.describe_all(ctx)
    data = {"providers": rows, "rclone_remotes": providers_mod.user_rclone_remotes(ctx)}

    def text(d):
        for p in d["providers"]:
            state = "connected" if p["connected"] else "-"
            print(f"{p['id']:<9} {p['name']:<28} {state:<10} {p['target']}")
        if d["rclone_remotes"]:
            print(f"Your rclone remotes (for `provider connect rclone --remote NAME`): {' '.join(d['rclone_remotes'])}")
    _out(args, data, text)
    return 0


def cmd_provider(ctx, args):
    def say(event):
        if args.json:
            print(json.dumps(event), flush=True)
        elif event.get("event") == "auth_url":
            print(f"Sign in here (opens in your browser): {event['url']}", flush=True)

    try:
        if args.action == "disconnect":
            if Engine.is_running(ctx.paths):
                raise ProviderError("a sync is running; try again when it finishes")
            res = providers_mod.disconnect(ctx, args.id)
            say({"event": "done", "ok": True, **res})
            if not args.json:
                print(f"Disconnected {args.id}. Files already stored there were left in place.")
            return 0
        kind = providers_mod.BY_ID.get(args.id, {}).get("kind")
        if kind == "folder":
            p = providers_mod.connect_folder(ctx, args.path)
        elif kind == "ssh":
            p = providers_mod.connect_ssh(ctx, args.host, args.path)
        elif kind == "rclone":
            p = providers_mod.connect_rclone(ctx, args.remote, args.folder)
        elif kind == "oauth":
            p = providers_mod.connect_oauth(ctx, args.id, args.folder, open_browser=not args.no_browser, emit=say)
        else:
            raise ProviderError(f"unknown provider: {args.id} ({', '.join(providers_mod.BY_ID)})")
        say({"event": "done", "ok": True, "id": p.id, "target": p.backend().describe()})
        if not args.json:
            print(f"Connected {p.name}: {p.backend().describe()}. The next sync includes it.")
        return 0
    except (ProviderError, BackendError) as e:
        say({"event": "done", "ok": False, "errors": [str(e)]})
        if not args.json:
            print(f"error: {e}", file=sys.stderr)
        return 1


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


def _ask(prompt, default=""):
    v = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return v or default


def cmd_setup(ctx, args):
    print("Extra Life setup: connect a place to keep your saves (run it again to add more; every sync uses all).")
    choices = providers_mod.CATALOG
    for i, c in enumerate(choices, 1):
        on = " (connected)" if c["id"] in (ctx.cfg.get("providers") or {}) else ""
        print(f"  {i}) {c['name']}{on}")
    try:
        c = choices[int(_ask(f"Choose 1-{len(choices)}", "1")) - 1]
    except (ValueError, IndexError):
        print("no such choice")
        return 1
    try:
        if c["kind"] == "folder":
            p = providers_mod.connect_folder(ctx, _ask("Folder (e.g. /run/media/deck/MyCard/ExtraLife)"))
        elif c["kind"] == "ssh":
            p = providers_mod.connect_ssh(ctx, _ask("SSH host (as in `ssh HOST`, key login)"), _ask("Folder on the host"))
        elif c["kind"] == "rclone":
            remotes = providers_mod.user_rclone_remotes(ctx)
            if not remotes:
                print("No rclone remotes yet: set one up with `rclone config`, then run setup again.")
                return 1
            print("rclone remotes: " + " ".join(remotes))
            p = providers_mod.connect_rclone(ctx, _ask("Remote", remotes[0]),
                                             _ask("Folder for Extra Life in it", providers_mod.DEFAULT_FOLDER))
        else:
            print(f"A browser opens to sign in to {c['name']}.")
            p = providers_mod.connect_oauth(ctx, c["id"], _ask("Folder for Extra Life in it",
                                                               providers_mod.DEFAULT_FOLDER),
                                            emit=lambda e: print(f"If no browser opened, go to: {e['url']}"))
    except (ProviderError, BackendError) as e:
        print(f"error: {e}")
        return 1
    print(f"Connected {p.name}: {p.backend().describe()}")
    if not ctx.cfg.get("device_name"):
        ctx.cfg["device_name"] = _ask("Name for this device", ctx.device.name)
        config_mod.save(ctx.paths.config_file, ctx.cfg)
    return cmd_doctor(Context.load(ctx.paths), args)


def cmd_doctor(ctx, args):
    ok = True
    print(f"Extra Life {__version__}; device {ctx.device.name} ({ctx.device.id})")
    print(f"Config: {ctx.paths.config_file}{'' if ctx.configured else ' (no provider connected)'}")
    for p in providers_mod.connected(ctx):
        try:
            b = p.backend()
            b.check()
            print(f"{p.name}: {b.describe()}: reachable")
        except BackendError as e:
            ok = False
            print(f"{p.name}: PROBLEM: {e}")
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
    for p in providers_mod.connected(ctx):
        removed = Engine(ctx, provider=p).prune()
        print(f"{p.name}: removed {len(removed)} old version folder(s).")
    return 0


def cmd_update_check(ctx, args):
    from . import update
    r = update.check(ctx.paths, force=args.force)

    def text(r):
        if r.get("error"):
            print(f"Extra Life {r['current']}: {r['error']}")
        elif r["newer"]:
            print(f"Extra Life {r['latest']} is available (you have {r['current']}): {r.get('url', '')}")
            print(f"Update in Desktop Mode with:\n  {r['command']}")
        else:
            print(f"Extra Life {r['current']} is up to date.")
    _out(args, r, text)
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

    p = add("sync", cmd_sync, "sync both ways with every connected provider (what the background service runs)")
    p.add_argument("--provider", action="append", help="only this provider (repeatable)")
    p.add_argument("--profile", action="append", help="only this emulator profile (repeatable)")
    p.add_argument("--dry-run", action="store_true", help="show what would change")
    p.add_argument("--wait", type=int, help="seconds to wait for running emulators to exit")
    p.add_argument("--lock-wait", type=int, default=0, help="seconds to wait if another run is in progress")
    p.add_argument("--quiet", action="store_true", help="print only problems")
    for name, fn, help in (("push", cmd_push, "force: make the providers match this device"),
                           ("pull", cmd_pull, "force: make this device match one provider")):
        p = add(name, fn, help)
        p.add_argument("--provider", action="append",
                       help="only this provider" + (" (repeatable)" if name == "push" else ""))
        p.add_argument("--profile", action="append", help="only this emulator profile (repeatable)")
        p.add_argument("--set", help="only this save folder (profile/set)")
        p.add_argument("--file", action="append", help="only this file in --set (repeatable)")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--lock-wait", type=int, default=30)
    add("status", cmd_status, "show the providers and the last sync")
    add("progress", cmd_progress, "progress of the running (or last) sync")
    p = add("recent", cmd_recent, "latest synced saves, newest first")
    p.add_argument("--limit", type=int, default=30)
    p = add("log", cmd_log, "what this device uploaded, downloaded or flagged")
    p.add_argument("--limit", type=int, default=50)
    add("conflicts", cmd_conflicts, "files changed on two devices")
    p = add("resolve", cmd_resolve, "settle conflicts by keeping one side")
    p.add_argument("--keep", choices=("local", "cloud"), required=True)
    p.add_argument("--provider")
    p.add_argument("--set")
    p.add_argument("--file")
    p.add_argument("--all", action="store_true")
    p = add("history", cmd_history, "older versions kept by a provider")
    p.add_argument("--provider")
    p.add_argument("--limit", type=int, default=30)
    p = add("restore", cmd_restore, "bring back an older version and make it the newest everywhere")
    p.add_argument("snapshot")
    p.add_argument("set")
    p.add_argument("file")
    p.add_argument("--provider", help="the provider whose history holds the version")
    add("providers", cmd_providers, "every storage provider and whether it is connected")
    p = add("provider", cmd_provider, "connect or disconnect a storage provider")
    p.add_argument("action", choices=("connect", "disconnect"))
    p.add_argument("id", help=", ".join(providers_mod.BY_ID))
    p.add_argument("--path", help="folder (local) or folder on the host (ssh)")
    p.add_argument("--host", help="ssh host")
    p.add_argument("--remote", help="rclone remote name (other rclone remote)")
    p.add_argument("--folder", help=f"folder inside the cloud storage (default {providers_mod.DEFAULT_FOLDER})")
    p.add_argument("--no-browser", action="store_true", help="don't open a browser; print the sign-in link")
    add("profiles", cmd_profiles, "emulators Extra Life knows and whether they sync")
    p = add("profile", cmd_profile, "turn an emulator on or off")
    p.add_argument("action", choices=("enable", "disable", "auto"))
    p.add_argument("id")
    p = add("config", cmd_config, "show or change settings (e.g. config set sync.include_states true)")
    p.add_argument("action", choices=("get", "set", "path"))
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    add("setup", cmd_setup, "connect a storage provider interactively", json_flag=False)
    add("doctor", cmd_doctor, "check the setup", json_flag=False)
    add("prune", cmd_prune, "delete versions older than sync.history_days now", json_flag=False)
    add("install-rclone", cmd_install_rclone, "download the official rclone build", json_flag=False)
    p = add("update-check", cmd_update_check, "is a newer Extra Life release available? (cached for 12 hours)")
    p.add_argument("--force", action="store_true", help="ask GitHub now")
    return ap


def main(argv=None):
    # SIGTERM (plugin cancels a sign-in, service stopped) unwinds normally so cleanup code runs.
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(143))
    args = build_parser().parse_args(argv)
    try:
        ctx = Context.load()
        return args.fn(ctx, args)
    except (config_mod.ConfigError, BackendError, EngineError, ProviderError) as e:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "errors": [str(e)]}))
        else:
            print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
