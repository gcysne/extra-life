"""Decky backend for Extra Life. Runs as the normal user (no "root" flag in plugin.json).

All the work is done by the `extralife` command (installed by install.sh); this file only runs it with --json and
starts the systemd user service for background syncs. Standard library only: Decky's bundled Python may lack
modules, and it leaks LD_LIBRARY_PATH into child processes (see _env()).
"""

import asyncio
import json
import os
import signal

import decky

HOME = decky.DECKY_USER_HOME
CLI = os.path.join(HOME, ".local/bin/extralife")
PROGRESS = os.path.join(HOME, ".local/state/extra-life/progress.json")
PROVIDER_IDS = ("gdrive", "dropbox", "onedrive", "box", "pcloud", "local", "ssh", "rclone")
SERVICE = "extralife-sync.service"
TIMER = "extralife-sync.timer"


def _env():
    uid = os.getuid()
    env = dict(os.environ, HOME=HOME, XDG_RUNTIME_DIR=f"/run/user/{uid}",
               DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{uid}/bus",
               LANG=os.environ.get("LANG", "C.UTF-8"))
    env["PATH"] = f"{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig:
        env["LD_LIBRARY_PATH"] = orig
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


async def _exec(*cmd, timeout=900):
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, env=_env())
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, b"", b"timed out"
    return proc.returncode, out, err


async def _cli(*args, timeout=900):
    if not os.access(CLI, os.X_OK):
        return {"ok": False, "not_installed": True,
                "errors": ["Extra Life isn't installed: run install.sh in Desktop Mode."]}
    code, out, err = await _exec(CLI, *args, "--json", timeout=timeout)
    try:
        return json.loads(out)
    except ValueError:
        msg = (err or out).decode("utf-8", "replace").strip()[-400:] or f"extralife exited with {code}"
        decky.logger.error(f"extralife {' '.join(args)}: {msg}")
        return {"ok": False, "errors": [msg]}


async def _systemctl(*args):
    code, out, err = await _exec("systemctl", "--user", *args, timeout=30)
    return code, out.decode().strip(), err.decode().strip()


def _public(auth):
    return {k: v for k, v in auth.items() if k not in ("proc", "task")}


def _alive(pid):
    try:
        pid = int(pid)
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


class Plugin:
    _auth = None

    async def progress(self):
        """Live sync progress, read straight from the file the CLI writes (no process start: polled every second)."""
        try:
            with open(PROGRESS, encoding="utf-8") as f:
                p = json.load(f)
        except (OSError, ValueError):
            return {"running": False}
        if p.get("running") and not _alive(p.get("pid")):
            p["running"], p["phase"] = False, "interrupted"
        return p

    async def update_check(self, force=False):
        return await _cli("update-check", *(["--force"] if force else []), timeout=60)

    async def providers(self):
        return await _cli("providers", timeout=60)

    async def volumes(self):
        """Mounted removable drives (SD cards, USB), for the folder provider."""
        out = []
        for base in (f"/run/media/{os.path.basename(HOME)}", "/run/media"):
            try:
                names = sorted(os.listdir(base))
            except OSError:
                continue
            for n in names:
                path = os.path.join(base, n)
                if not os.path.ismount(path) or any(v["path"] == path for v in out):
                    continue
                try:
                    st = os.statvfs(path)
                    free, total = st.f_bavail * st.f_frsize, st.f_blocks * st.f_frsize
                except OSError:
                    free = total = 0
                out.append({"name": n, "path": path, "free": free, "total": total,
                            "writable": os.access(path, os.W_OK)})
        return out

    async def connect(self, provider, kind, options=None):
        """Connect a provider. Sign-in providers start the browser flow and return its link at once; the result
        comes later through connect_status()."""
        o = options or {}
        if provider not in PROVIDER_IDS:
            return {"ok": False, "errors": ["unknown provider"]}
        folder = ["--folder", str(o["folder"])] if o.get("folder") else []
        if kind != "oauth":
            args = ["provider", "connect", provider, *folder]
            for key in ("path", "host", "remote"):
                if o.get(key):
                    args += [f"--{key}", str(o[key])]
            return await self._connect_blocking(args)
        await self.connect_cancel()
        if not os.access(CLI, os.X_OK):
            return {"ok": False, "errors": ["Extra Life isn't installed"]}
        proc = await asyncio.create_subprocess_exec(
            CLI, "provider", "connect", provider, *folder, "--json", "--no-browser",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=_env(), start_new_session=True)
        auth = {"provider": provider, "state": "starting", "url": "", "errors": [], "proc": proc}
        self._auth = auth

        async def pump():
            async for raw in proc.stdout:
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                if ev.get("event") == "auth_url":
                    auth.update(url=ev["url"], state="waiting")
                elif ev.get("event") == "done":
                    auth.update(state="done" if ev.get("ok") else "error", errors=ev.get("errors", []),
                                target=ev.get("target", ""))
            err = (await proc.stderr.read()).decode("utf-8", "replace").strip()
            await proc.wait()
            if auth["state"] not in ("done", "error", "cancelled"):
                auth.update(state="error", errors=[err[-300:] or f"sign-in ended ({proc.returncode})"])

        auth["task"] = asyncio.create_task(pump())
        for _ in range(900):                     # the first sign-in may download rclone first
            if auth["state"] != "starting":
                break
            await asyncio.sleep(0.1)
        return {"ok": auth["state"] != "error", **_public(auth)}

    async def _connect_blocking(self, args):
        code, out, err = await _exec(CLI, *args, "--json", timeout=180)
        events = []
        for line in out.decode("utf-8", "replace").splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        done = next((e for e in reversed(events) if e.get("event") == "done"), None)
        if done:
            return done
        return {"ok": False, "errors": [err.decode("utf-8", "replace").strip()[-300:] or f"exit {code}"]}

    async def connect_status(self):
        return _public(self._auth) if self._auth else {"state": "idle"}

    async def connect_cancel(self):
        auth, self._auth = self._auth, None
        if auth and auth["proc"].returncode is None:
            auth["state"] = "cancelled"
            try:
                os.killpg(auth["proc"].pid, signal.SIGTERM)   # the CLI and the rclone it started
            except ProcessLookupError:
                pass
        return {"ok": True}

    async def disconnect(self, provider):
        if provider not in PROVIDER_IDS:
            return {"ok": False, "errors": ["unknown provider"]}
        return await self._connect_blocking(["provider", "disconnect", provider])

    async def status(self):
        s = await _cli("status", timeout=60)
        if isinstance(s, dict):
            code, out, _ = await _systemctl("is-enabled", TIMER)
            s["timer_enabled"] = code == 0
            code, out, _ = await _systemctl("is-active", SERVICE)
            s["service_active"] = out in ("active", "activating")
            s["running"] = s.get("running") or s["service_active"]
        return s

    async def recent(self, limit=30):
        return await _cli("recent", "--limit", str(int(limit)), timeout=60)

    async def activity(self, limit=50):
        return await _cli("log", "--limit", str(int(limit)), timeout=60)

    async def history(self, limit=30, provider=None):
        extra = ["--provider", provider] if provider else []
        return await _cli("history", "--limit", str(int(limit)), *extra, timeout=300)

    async def profiles(self):
        return await _cli("profiles", timeout=60)

    async def set_profile(self, profile_id, action):
        if action not in ("enable", "disable", "auto"):
            return {"ok": False, "errors": ["bad action"]}
        return await _cli("profile", action, str(profile_id), timeout=60)

    async def set_setting(self, key, value):
        allowed = {"sync.on_game_exit", "sync.include_states", "sync.propagate_deletes"}
        if key not in allowed:
            return {"ok": False, "errors": [f"{key} can't be changed from the plugin"]}
        return await _cli("config", "set", key, "true" if value else "false", timeout=60)

    async def set_timer(self, enabled):
        code, _, err = await _systemctl("enable" if enabled else "disable", "--now", TIMER)
        return {"ok": code == 0, "errors": [err] if code else []}

    async def sync_now(self):
        """Background sync through the systemd service (survives the plugin being reloaded)."""
        code, _, err = await _systemctl("start", "--no-block", SERVICE)
        return {"ok": code == 0, "errors": [err] if code else []}

    async def game_exited(self, app_id):
        cfg = await _cli("config", "get", "sync.on_game_exit", timeout=60)
        if cfg is True:
            decky.logger.info(f"game {app_id} exited: starting a sync")
            return await self.sync_now()
        return {"ok": True, "skipped": True}

    async def resumed(self):
        return await self.sync_now()

    async def push(self, set_key=None, profile=None):
        args = ["push"] + (["--set", set_key] if set_key else []) + (["--profile", profile] if profile else [])
        return await _cli(*args)

    async def pull(self, set_key=None, profile=None, provider=None):
        args = ["pull"] + (["--set", set_key] if set_key else []) + (["--profile", profile] if profile else [])
        return await _cli(*args, *(["--provider", provider] if provider else []))

    async def resolve(self, keep, set_key=None, rel=None, provider=None):
        if keep not in ("local", "cloud"):
            return {"ok": False, "errors": ["bad side"]}
        args = ["resolve", "--keep", keep] + (["--set", set_key, "--file", rel] if set_key and rel else ["--all"])
        return await _cli(*args, *(["--provider", provider] if provider else []))

    async def restore(self, snapshot, set_key, rel, provider=None):
        return await _cli("restore", snapshot, set_key, rel, *(["--provider", provider] if provider else []))

    async def _main(self):
        decky.logger.info("Extra Life backend loaded")

    async def _unload(self):
        await self.connect_cancel()
