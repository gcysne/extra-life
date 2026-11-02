"""Storage providers: the catalog shown to the user, connecting and disconnecting.

A provider is connected when it has a [providers.<id>] table in config.toml; every sync runs against all connected
providers. Cloud sign-ins made here go into Extra Life's own rclone.conf (paths.rclone_conf), so disconnecting can
delete them without touching remotes the user set up for other things with `rclone config`.
"""

import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field

from . import config as config_mod
from .backends import BackendError, make_backend
from .backends.base import clean_env

CATALOG = [
    {"id": "gdrive", "name": "Google Drive", "kind": "oauth", "rclone_type": "drive", "params": {"scope": "drive.file"}},
    {"id": "dropbox", "name": "Dropbox", "kind": "oauth", "rclone_type": "dropbox"},
    {"id": "onedrive", "name": "OneDrive", "kind": "oauth", "rclone_type": "onedrive"},
    {"id": "box", "name": "Box", "kind": "oauth", "rclone_type": "box"},
    {"id": "pcloud", "name": "pCloud", "kind": "oauth", "rclone_type": "pcloud"},
    {"id": "local", "name": "Folder (SD card, USB drive)", "kind": "folder"},
    {"id": "ssh", "name": "NAS or computer (SSH)", "kind": "ssh"},
    {"id": "rclone", "name": "Other rclone remote", "kind": "rclone"},
]
BY_ID = {c["id"]: c for c in CATALOG}
DEFAULT_FOLDER = "ExtraLife"
AUTH_URL = re.compile(r"(http://(?:127\.0\.0\.1|localhost):\d+/auth\?state=[\w-]+)")
AUTH_TIMEOUT = 600


class ProviderError(Exception):
    pass


@dataclass
class Provider:
    id: str
    name: str
    kind: str
    cfg: dict = field(default_factory=dict)

    def backend(self):
        return make_backend(self.cfg)


def connected(ctx, only=None):
    """Connected providers, catalog order first."""
    cfgs = ctx.cfg.get("providers") or {}
    ids = [c["id"] for c in CATALOG if c["id"] in cfgs] + [i for i in cfgs if i not in BY_ID]
    out = []
    for pid in ids:
        if only and pid not in only:
            continue
        meta = BY_ID.get(pid, {"name": pid, "kind": cfgs[pid].get("type", "")})
        out.append(Provider(pid, meta["name"], meta["kind"], dict(cfgs[pid])))
    return out


def get(ctx, pid):
    for p in connected(ctx):
        if p.id == pid:
            return p
    raise ProviderError(f"{pid} is not connected")


def _save(ctx, pid, pcfg):
    make_backend(pcfg).check()            # validates the settings and creates the folder
    ctx.cfg.setdefault("providers", {})[pid] = pcfg
    config_mod.save(ctx.paths.config_file, ctx.cfg)
    return Provider(pid, BY_ID.get(pid, {}).get("name", pid), BY_ID.get(pid, {}).get("kind", ""), pcfg)


def _folder(folder):
    folder = (folder or DEFAULT_FOLDER).strip().strip("/")
    if not folder or ".." in folder.split("/"):
        raise ProviderError("give a folder name, e.g. ExtraLife")
    return folder


def connect_folder(ctx, path):
    path = os.path.expanduser((path or "").strip())
    if not path:
        raise ProviderError("choose a folder")
    return _save(ctx, "local", {"type": "local", "path": path})


def connect_ssh(ctx, host, path):
    if not (host or "").strip() or not (path or "").strip():
        raise ProviderError("give the host (as in `ssh HOST`) and a folder on it")
    return _save(ctx, "ssh", {"type": "rsync-ssh", "host": host.strip(), "path": path.strip()})


def rclone_bin(ctx, install=False):
    from .backends.rclone import find_rclone
    rc = find_rclone()
    if not rc and install:
        from .rclone_install import install as do_install
        rc = do_install(log=lambda m: None)
    if not rc:
        raise ProviderError("rclone isn't installed; run `extralife install-rclone`")
    return rc


def user_rclone_remotes(ctx):
    """Remotes in the user's own rclone.conf (for "Other rclone remote")."""
    try:
        rc = rclone_bin(ctx)
    except ProviderError:
        return []
    p = subprocess.run([rc, "listremotes"], capture_output=True, text=True, env=clean_env(), timeout=30)
    return [r.rstrip(":") for r in p.stdout.split() if r.endswith(":")]


def connect_rclone(ctx, remote, folder=""):
    remote = (remote or "").strip().rstrip(":")
    if not remote:
        raise ProviderError("choose an rclone remote")
    if remote not in user_rclone_remotes(ctx):
        raise ProviderError(f"{remote}: no such remote in rclone.conf (set it up with `rclone config`)")
    return _save(ctx, "rclone", {"type": "rclone", "remote": f"{remote}:{_folder(folder)}"})


def connect_oauth(ctx, pid, folder="", open_browser=True, emit=lambda event: None, cancel=None):
    """Sign in through rclone's browser flow. emit({"event": "auth_url", "url": ...}) as soon as the sign-in page
    is ready; returns when the user finished signing in (or raises ProviderError)."""
    meta = BY_ID.get(pid)
    if not meta or meta["kind"] != "oauth":
        raise ProviderError(f"{pid} is not a sign-in provider")
    folder = _folder(folder)
    rc = rclone_bin(ctx, install=True)
    conf = str(ctx.paths.rclone_conf)
    ctx.paths.config_dir.mkdir(parents=True, exist_ok=True)
    env = clean_env()
    stub_dir = None
    if not open_browser:
        # rclone always tries xdg-open; the caller shows the link itself (e.g. in Steam's browser).
        stub_dir = tempfile.mkdtemp(prefix="extralife-nobrowser-")
        stub = os.path.join(stub_dir, "xdg-open")
        with open(stub, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(stub, 0o755)
        env["PATH"] = f"{stub_dir}:{env.get('PATH', '/usr/bin:/bin')}"
    subprocess.run([rc, "--config", conf, "config", "delete", pid], capture_output=True, env=env, timeout=30)
    params = [f"{k}={v}" for k, v in meta.get("params", {}).items()]
    proc = subprocess.Popen([rc, "--config", conf, "config", "create", pid, meta["rclone_type"], *params],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    tail = []

    def reader():
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            m = AUTH_URL.search(line)
            if m:
                emit({"event": "auth_url", "url": m.group(1)})
            elif line and "token" not in line.lower():     # never echo the token rclone prints at the end
                tail.append(line)
                del tail[:-5]

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    deadline = time.monotonic() + AUTH_TIMEOUT
    signed_in = False
    try:
        while proc.poll() is None:
            if time.monotonic() > deadline or (cancel and cancel()):
                proc.kill()
                proc.wait()
                raise ProviderError("sign-in cancelled" if cancel and cancel() else "sign-in timed out")
            time.sleep(0.3)
        t.join(5)
        if proc.returncode != 0:
            raise ProviderError(f"sign-in failed: {' | '.join(tail[-2:]) or f'rclone exited with {proc.returncode}'}")
        signed_in = True
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        if not signed_in:
            # rclone writes the remote before the sign-in finishes: never leave a half-made one behind
            # (this also runs when the plugin cancels the sign-in with SIGTERM).
            subprocess.run([rc, "--config", conf, "config", "delete", pid], capture_output=True, env=env, timeout=30)
        if stub_dir:
            try:
                os.unlink(os.path.join(stub_dir, "xdg-open"))
                os.rmdir(stub_dir)
            except OSError:
                pass
    try:
        os.chmod(conf, 0o600)
    except OSError:
        pass
    try:
        return _save(ctx, pid, {"type": "rclone", "remote": f"{pid}:{folder}", "rclone_config": conf})
    except BackendError as e:
        raise ProviderError(f"signed in, but the folder can't be used: {e}") from e


def disconnect(ctx, pid):
    """Stop syncing with a provider and forget its sign-in (if Extra Life made it). Files already stored there and
    this device's sync state for it are kept, so reconnecting later picks up where it left off."""
    provs = ctx.cfg.get("providers") or {}
    if pid not in provs:
        raise ProviderError(f"{pid} is not connected")
    pcfg = provs.pop(pid)
    config_mod.save(ctx.paths.config_file, ctx.cfg)
    removed_login = False
    conf = pcfg.get("rclone_config")
    if pcfg.get("type") == "rclone" and conf and os.path.abspath(conf) == os.path.abspath(ctx.paths.rclone_conf):
        name = pcfg.get("remote", "").partition(":")[0]
        try:
            rc = rclone_bin(ctx)
            p = subprocess.run([rc, "--config", conf, "config", "delete", name], capture_output=True,
                               env=clean_env(), timeout=30)
            removed_login = p.returncode == 0
        except ProviderError:
            pass
    return {"id": pid, "removed_login": removed_login}


def describe_all(ctx):
    """Every catalog entry with its state, for the plugin's provider list."""
    from .util import read_json
    cfgs = ctx.cfg.get("providers") or {}
    out = []
    for c in CATALOG + [{"id": i, "name": i, "kind": cfgs[i].get("type", "")} for i in cfgs if i not in BY_ID]:
        row = {"id": c["id"], "name": c["name"], "kind": c["kind"], "connected": c["id"] in cfgs, "target": ""}
        if row["connected"]:
            try:
                row["target"] = make_backend(cfgs[c["id"]]).describe()
            except BackendError as e:
                row["error"] = str(e)
            last = read_json(ctx.paths.for_provider(c["id"]).last_run_file)
            if last:
                row["last_run"] = {k: last.get(k) for k in ("mode", "finished", "ok", "errors", "summary")}
        out.append(row)
    return out
