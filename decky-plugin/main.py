"""Decky backend for Extra Life. Runs as the normal user (no "root" flag in plugin.json).

All the work is done by the `extralife` command (installed by install.sh); this file only runs it with --json and
starts the systemd user service for background syncs. Standard library only: Decky's bundled Python may lack
modules, and it leaks LD_LIBRARY_PATH into child processes (see _env()).
"""

import asyncio
import json
import os

import decky

HOME = decky.DECKY_USER_HOME
CLI = os.path.join(HOME, ".local/bin/extralife")
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


class Plugin:
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

    async def history(self, limit=30):
        return await _cli("history", "--limit", str(int(limit)), timeout=300)

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

    async def pull(self, set_key=None, profile=None):
        args = ["pull"] + (["--set", set_key] if set_key else []) + (["--profile", profile] if profile else [])
        return await _cli(*args)

    async def resolve(self, keep, set_key=None, rel=None):
        if keep not in ("local", "cloud"):
            return {"ok": False, "errors": ["bad side"]}
        args = ["resolve", "--keep", keep] + (["--set", set_key, "--file", rel] if set_key and rel else ["--all"])
        return await _cli(*args)

    async def restore(self, snapshot, set_key, rel):
        return await _cli("restore", snapshot, set_key, rel)

    async def _main(self):
        decky.logger.info("Extra Life backend loaded")

    async def _unload(self):
        pass
