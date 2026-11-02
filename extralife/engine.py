"""The sync engine.

For every save folder ("set") it compares three states of each file by SHA-256:
  local  - the folder on this device now
  remote - the remote manifest now (written by whichever device synced last)
  base   - the remote manifest as this device left it after its last sync
Only local changed -> upload. Only remote changed -> download. Both changed differently -> conflict: nothing is
touched for that file until the user picks a side. Nothing is ever lost: a remote version that gets replaced or
deleted is kept under history/, a local file that gets replaced or deleted is copied to the local backup folder.

Modes: "sync" (both ways), "push" (force: upload every local file that differs, the cloud copy goes to history)
and "pull" (force: download every remote file that differs, the local copy goes to the backup folder). Forced
modes never delete files on the other side.
"""

import fcntl
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from . import REMOTE_FORMAT, profiles as profiles_mod, procs
from .backends import BackendError, make_backend
from .scan import scan, sha256_file
from .util import iso, parse_iso, parse_stamp, read_json, slug, stamp, utcnow, write_json

LOCK_MINUTES = 15
PRUNE_EVERY_HOURS = 24
MAX_EVENTS = 3000


class Busy(Exception):
    pass


class EngineError(Exception):
    pass


@dataclass
class Plan:
    uploads: list = field(default_factory=list)
    downloads: list = field(default_factory=list)
    remote_deletes: list = field(default_factory=list)
    local_deletes: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    keep_base: list = field(default_factory=list)   # paths whose base must not move (conflicts, skipped deletes)

    def empty(self):
        return not (self.uploads or self.downloads or self.remote_deletes or self.local_deletes)


def plan_set(local, remote, base, mode="sync", propagate_deletes=True, only=None):
    """local: {rel: FileInfo}; remote, base: {rel: manifest entry}. Pure function, see module docstring."""
    plan = Plan()
    for rel in sorted(set(local) | set(remote) | set(base)):
        if only is not None and rel not in only:
            plan.keep_base.append(rel)
            continue
        ls = local[rel].sha256 if rel in local else None
        rs = remote[rel]["sha256"] if rel in remote else None
        bs = base[rel]["sha256"] if rel in base else None
        if ls == rs:
            continue
        if mode == "push":                # never deletes on the remote; untouched paths keep their base
            if ls is not None:
                plan.uploads.append(rel)
            else:
                plan.keep_base.append(rel)
            continue
        if mode == "pull":                # never deletes on this device
            if rs is not None:
                plan.downloads.append(rel)
            else:
                plan.keep_base.append(rel)
            continue
        if rs == bs:                      # only this device changed it
            if ls is not None:
                plan.uploads.append(rel)
            elif propagate_deletes:
                plan.remote_deletes.append(rel)
            else:
                plan.keep_base.append(rel)
        elif ls == bs:                    # only the remote changed it
            if rs is not None:
                plan.downloads.append(rel)
            elif propagate_deletes:
                plan.local_deletes.append(rel)
            else:
                plan.keep_base.append(rel)
        else:
            plan.conflicts.append(rel)
            plan.keep_base.append(rel)
    return plan


class Engine:
    def __init__(self, ctx, backend=None, log=None):
        self.ctx = ctx
        self.paths = ctx.paths
        self.backend = backend
        self.log = log or (lambda msg: None)
        self._lock_fd = None

    # ---------- locks ----------

    def _local_lock(self, wait):
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.paths.lock_file, os.O_RDWR | os.O_CREAT, 0o644)
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._lock_fd = fd
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise Busy("another Extra Life run is in progress on this device")
                time.sleep(1)

    def _local_unlock(self):
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    @staticmethod
    def is_running(paths):
        try:
            fd = os.open(paths.lock_file, os.O_RDWR)
        except FileNotFoundError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True
        finally:
            os.close(fd)

    def _remote_lock(self):
        b, dev = self.backend, self.ctx.device
        raw = b.read_text("lock.json")
        if raw:
            try:
                lock = json.loads(raw)
            except ValueError:
                lock = {}
            expires = parse_iso(lock.get("expires"))
            if lock.get("device_id") != dev.id and expires and expires > utcnow():
                raise Busy(f"{lock.get('device', 'another device')} is syncing right now; try again in a few minutes")
        b.write_text("lock.json", json.dumps({
            "device": dev.name, "device_id": dev.id, "since": iso(),
            "expires": iso(utcnow() + timedelta(minutes=LOCK_MINUTES))}) + "\n")

    def _remote_unlock(self):
        try:
            raw = self.backend.read_text("lock.json")
            if raw and json.loads(raw).get("device_id") == self.ctx.device.id:
                self.backend.delete("lock.json")
        except (BackendError, ValueError):
            pass

    def _check_format(self):
        raw = self.backend.read_text("extra-life.json")
        if raw is None:
            self.backend.write_text("extra-life.json", json.dumps(
                {"app": "Extra Life", "format": REMOTE_FORMAT, "created": iso()}, indent=1) + "\n")
            return
        try:
            fmt = json.loads(raw).get("format", 0)
        except ValueError as e:
            raise EngineError("extra-life.json on the remote is damaged") from e
        if fmt > REMOTE_FORMAT:
            raise EngineError(f"the remote uses format {fmt}; update Extra Life on this device")

    # ---------- state files ----------

    def _base_file(self, key):
        return self.paths.base_dir / f"{key.replace('/', '__')}.json"

    def _cache_file(self, key):
        return self.paths.cache_dir / f"{key.replace('/', '__')}.json"

    def load_base(self, key):
        return (read_json(self._base_file(key), {}) or {}).get("files", {})

    def _save_base(self, key, files):
        write_json(self._base_file(key), {"set": key, "files": files, "synced": iso()})

    def _events(self, events):
        if not events:
            return
        f = self.paths.events_file
        f.parent.mkdir(parents=True, exist_ok=True)
        with open(f, "a", encoding="utf-8") as out:
            for e in events:
                out.write(json.dumps(e, sort_keys=True) + "\n")
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
            if len(lines) > MAX_EVENTS:
                f.write_text("\n".join(lines[-MAX_EVENTS // 2:]) + "\n", encoding="utf-8")
        except OSError:
            pass

    # ---------- main entry ----------

    def run(self, mode="sync", only_profiles=None, only_rels=None, only_set=None, dry_run=False, wait=0,
            lock_wait=0):
        if mode not in ("sync", "push", "pull"):
            raise ValueError(mode)
        report = {"mode": mode, "device": self.ctx.device.name, "started": iso(), "dry_run": dry_run,
                  "sets": [], "errors": [], "ok": False}
        self._local_lock(lock_wait)
        try:
            if self.backend is None:
                self.backend = make_backend(self.ctx.cfg)
            report["remote"] = self.backend.describe()
            errors = []
            sets = profiles_mod.resolve(self.ctx, errors, only=only_profiles)
            if only_set:
                sets = [s for s in sets if s.key == only_set]
                if not sets:
                    raise EngineError(f"{only_set}: no such save folder on this device")
            report["warnings"] = errors
            if wait and mode != "push":
                self._wait_for_emulators(sets, wait)
            self.backend.check()
            self._check_format()
            if not dry_run:
                self._remote_lock()
            try:
                snap = f"{stamp()}_{slug(self.ctx.device.name)}"
                with tempfile.TemporaryDirectory(dir=self._tmp_root()) as tmp:
                    tmp = Path(tmp)
                    self.backend.fetch_tree("manifests", tmp / "manifests")
                    for s in sets:
                        report["sets"].append(self._run_set(s, mode, tmp, snap, only_rels, dry_run))
                if not dry_run:
                    self._touch_device()
                    self._maybe_prune(report)
            finally:
                if not dry_run:
                    self._remote_unlock()
            report["errors"] += [f"{r['key']}: {r['error']}" for r in report["sets"] if r.get("error")]
            report["ok"] = not report["errors"]
        except (BackendError, EngineError, Busy, OSError) as e:
            report["errors"].append(str(e))
            report["fatal"] = True
        finally:
            report["finished"] = iso()
            if not dry_run:
                self._finish(report)
            self._local_unlock()
        return report

    def _tmp_root(self):
        self.paths.tmp_dir.mkdir(parents=True, exist_ok=True)
        return self.paths.tmp_dir

    def _wait_for_emulators(self, sets, wait):
        deadline = time.monotonic() + wait
        procs_needed = {p for s in sets for p in s.processes}
        while procs_needed and procs.is_running(procs_needed) and time.monotonic() < deadline:
            time.sleep(2)

    def _run_set(self, s, mode, tmp, snap, only_rels, dry_run):
        r = {"key": s.key, "name": s.profile_name, "kind": s.kind, "uploaded": [], "downloaded": [],
             "remote_deleted": [], "local_deleted": [], "conflicts": [], "skipped": ""}
        if mode != "push" and procs.is_running(s.processes):
            r["skipped"] = "emulator is running"
            return r
        try:
            manifest_rel = f"manifests/{s.key}.json"
            mf = read_json(tmp / manifest_rel, {}) or {}
            remote = mf.get("files", {})
            base = self.load_base(s.key)
            local = scan(s.root, s.include, s.exclude, self._cache_file(s.key))
            plan = plan_set(local, remote, base, mode, self.ctx.cfg["sync"].get("propagate_deletes", True),
                            set(only_rels) if only_rels else None)
            r.update(uploaded=plan.uploads, downloaded=plan.downloads, remote_deleted=plan.remote_deletes,
                     local_deleted=plan.local_deletes, conflicts=plan.conflicts)
            if dry_run:
                return r
            new_remote = self._apply(s, plan, local, remote, snap, tmp, r)
            if new_remote != remote:
                self.backend.write_text(manifest_rel, json.dumps(
                    {"set": s.key, "files": new_remote, "updated": iso(), "device": self.ctx.device.name},
                    indent=0, sort_keys=True) + "\n")
            new_base = dict(new_remote)
            for rel in plan.keep_base:
                if rel in base:
                    new_base[rel] = base[rel]
                else:
                    new_base.pop(rel, None)
            self._save_base(s.key, new_base)
            self._update_conflicts(s, mode, plan, local, remote, only_rels)
        except (BackendError, EngineError, OSError) as e:
            r["error"] = str(e)
        return r

    def _apply(self, s, plan, local, remote, snap, tmp, r):
        b, dev, now = self.backend, self.ctx.device, iso()
        data_dir, hist_dir = f"data/{s.key}", f"history/{snap}/{s.key}"
        new_remote = dict(remote)
        events = []

        def ev(action, rel, size=None, **extra):
            events.append({"time": now, "device": dev.name, "action": action, "key": s.key, "name": s.profile_name,
                           "rel": rel, "size": size, **extra})

        if plan.uploads:
            replaced = [f for f in plan.uploads if f in remote]
            b.copy(data_dir, hist_dir, replaced)
            b.upload(s.root, data_dir, plan.uploads)
            for f in plan.uploads:
                li = local[f]
                new_remote[f] = {"sha256": li.sha256, "size": li.size, "mtime_ns": li.mtime_ns,
                                 "device": dev.name, "time": now}
                ev("upload", f, li.size)
        if plan.remote_deletes:
            b.move(data_dir, hist_dir, plan.remote_deletes)
            for f in plan.remote_deletes:
                new_remote.pop(f, None)
                ev("remote_delete", f)
        backup = self.paths.backup_dir / snap / s.key
        if plan.downloads:
            staging = tmp / "download" / s.key
            b.download(data_dir, staging, plan.downloads)
            failed = []
            for f in plan.downloads:
                entry = remote[f]
                got = staging / f
                if not got.is_file() or sha256_file(got) != entry["sha256"]:
                    failed.append(f)
                    continue
                target = s.root / f
                if target.exists():
                    _backup(target, backup / f)
                _place(got, target, entry.get("mtime_ns"))
                ev("download", f, entry.get("size"), source=entry.get("device"))
            if failed:
                r["downloaded"] = [f for f in plan.downloads if f not in failed]
                r["error"] = f"{len(failed)} file(s) didn't match the manifest and were left alone: {failed[:3]}"
        for f in plan.local_deletes:
            target = s.root / f
            if target.exists():
                _backup(target, backup / f, move=True)
            ev("local_delete", f)
        for f in plan.conflicts:
            ev("conflict", f, local[f].size if f in local else None,
               other=remote.get(f, {}).get("device", ""))
        self._events(events)
        return new_remote

    def _update_conflicts(self, s, mode, plan, local, remote, only_rels):
        data = read_json(self.paths.conflicts_file, {}) or {}
        cur = data.get(s.key, {})
        if mode == "sync" and only_rels is None:
            cur = {}
        else:
            for rel in plan.uploads + plan.downloads:
                cur.pop(rel, None)
            if mode != "sync":
                for rel in list(cur):
                    if only_rels is None or rel in only_rels:
                        cur.pop(rel, None)
        for rel in plan.conflicts:
            li, re_ = local.get(rel), remote.get(rel)
            cur[rel] = {"local": {"sha256": li.sha256, "size": li.size, "mtime_ns": li.mtime_ns} if li else None,
                        "remote": re_, "detected": iso()}
        if cur:
            data[s.key] = cur
        else:
            data.pop(s.key, None)
        write_json(self.paths.conflicts_file, data)

    def _touch_device(self):
        dev = self.ctx.device
        self.backend.write_text(f"devices/{dev.id}.json", json.dumps(
            {"id": dev.id, "name": dev.name, "last_sync": iso()}, indent=1) + "\n")

    def _finish(self, report):
        summary = {k: sum(len(s.get(k, [])) for s in report["sets"])
                   for k in ("uploaded", "downloaded", "remote_deleted", "local_deleted", "conflicts")}
        report["summary"] = summary
        write_json(self.paths.last_run_file, report)

    # ---------- retention ----------

    def _maybe_prune(self, report):
        last = parse_iso((read_json(self.paths.prune_file, {}) or {}).get("time"))
        if last and utcnow() - last < timedelta(hours=PRUNE_EVERY_HOURS):
            return
        try:
            self.prune()
        except (BackendError, OSError) as e:
            report.setdefault("warnings", []).append(f"pruning old versions failed: {e}")

    def prune(self):
        sync = self.ctx.cfg["sync"]
        removed = []
        cutoff = utcnow() - timedelta(days=int(sync.get("history_days", 30)))
        for name in self.backend.list_dirs("history"):
            t = parse_stamp(name)
            if t and t < cutoff:
                self.backend.purge(f"history/{name}")
                removed.append(f"history/{name}")
        cutoff = utcnow() - timedelta(days=int(sync.get("backup_days", 30)))
        if self.paths.backup_dir.is_dir():
            for d in self.paths.backup_dir.iterdir():
                t = parse_stamp(d.name)
                if d.is_dir() and t and t < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
                    removed.append(str(d))
        write_json(self.paths.prune_file, {"time": iso(), "removed": len(removed)})
        return removed

    # ---------- history and restore ----------

    def history(self, limit=50):
        if self.backend is None:
            self.backend = make_backend(self.ctx.cfg)
        snaps = {}
        for rel, size in self.backend.list_files("history"):
            name, _, rest = rel.partition("/")
            parts = rest.split("/", 2)
            if len(parts) < 3:
                continue
            snaps.setdefault(name, []).append({"key": f"{parts[0]}/{parts[1]}", "rel": parts[2], "size": size})
        out = []
        for name in sorted(snaps, reverse=True)[:limit]:
            t = parse_stamp(name)
            out.append({"id": name, "time": iso(t) if t else "", "device": name.partition("_")[2],
                        "files": snaps[name]})
        return out

    def restore(self, snapshot, key, rel):
        """Put an older version from history back in place on this device, then push it as the newest."""
        if self.backend is None:
            self.backend = make_backend(self.ctx.cfg)
        sets = {s.key: s for s in profiles_mod.resolve(self.ctx)}
        s = sets.get(key)
        if not s:
            raise EngineError(f"{key}: no such save folder on this device")
        if procs.is_running(s.processes):
            raise EngineError(f"{s.profile_name} is running; close it first")
        self._local_lock(30)
        try:
            with tempfile.TemporaryDirectory(dir=self._tmp_root()) as tmp:
                staging = Path(tmp)
                self.backend.download(f"history/{snapshot}/{key}", staging, [rel])
                got = staging / rel
                if not got.is_file():
                    raise EngineError(f"{rel} is not in {snapshot}")
                target = s.root / rel
                if target.exists():
                    _backup(target, self.paths.backup_dir / f"{stamp()}_restore" / key / rel)
                _place(got, target, None)
        finally:
            self._local_unlock()
        self._events([{"time": iso(), "device": self.ctx.device.name, "action": "restore", "key": key,
                       "name": s.profile_name, "rel": rel, "size": None, "snapshot": snapshot}])
        return self.run("push", only_set=key, only_rels=[rel])


def _backup(src, dst, move=False):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(str(src), str(dst))
    else:
        shutil.copy2(src, dst)


def _place(staged, target, mtime_ns):
    """Copy a downloaded file next to the target, then swap it in with one rename."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".extralife-tmp-{target.name}")
    shutil.copyfile(staged, tmp)
    if target.exists():
        shutil.copymode(target, tmp)
    if mtime_ns:
        os.utime(tmp, ns=(mtime_ns, mtime_ns))
    os.replace(tmp, target)
