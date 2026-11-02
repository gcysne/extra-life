"""Where Extra Life keeps its files, and the per-run context (paths, config, this device)."""

import os
import shutil
import socket
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import config as config_mod
from .util import read_json, write_json

APP_DIR = "extra-life"
SHIPPED_PROFILES = Path(__file__).resolve().parent.parent / "profiles"


def _xdg(var, fallback):
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / fallback


@dataclass
class Paths:
    config_dir: Path
    state_dir: Path
    shipped_profiles: Path = SHIPPED_PROFILES
    provider: str = ""          # set by for_provider(): the sync state below is kept per provider

    @classmethod
    def default(cls):
        cfg = os.environ.get("EXTRALIFE_CONFIG_DIR")
        state = os.environ.get("EXTRALIFE_STATE_DIR")
        return cls(Path(cfg) if cfg else _xdg("XDG_CONFIG_HOME", ".config") / APP_DIR,
                   Path(state) if state else _xdg("XDG_STATE_HOME", ".local/state") / APP_DIR)

    def for_provider(self, provider_id):
        return replace(self, provider=provider_id)

    @property
    def provider_dir(self):
        return self.state_dir / "providers" / self.provider if self.provider else self.state_dir

    config_file = property(lambda s: s.config_dir / "config.toml")
    rclone_conf = property(lambda s: s.config_dir / "rclone.conf")   # sign-ins made through Extra Life
    user_profiles = property(lambda s: s.config_dir / "profiles")
    cache_dir = property(lambda s: s.state_dir / "hashcache")
    backup_dir = property(lambda s: s.state_dir / "backup")        # local files replaced or removed by a sync
    tmp_dir = property(lambda s: s.state_dir / "tmp")
    events_file = property(lambda s: s.state_dir / "events.jsonl")
    device_file = property(lambda s: s.state_dir / "device.json")
    lock_file = property(lambda s: s.state_dir / "lock")
    progress_file = property(lambda s: s.state_dir / "progress.json")
    # per provider (the run summary of all providers is the state_dir one)
    base_dir = property(lambda s: s.provider_dir / "base")         # remote manifests as of the last sync
    conflicts_file = property(lambda s: s.provider_dir / "conflicts.json")
    last_run_file = property(lambda s: s.provider_dir / "last-run.json")
    prune_file = property(lambda s: s.provider_dir / "last-prune.json")
    remote_file = property(lambda s: s.provider_dir / "remote.json")   # which remote the base belongs to


@dataclass
class Device:
    id: str
    name: str


@dataclass
class Context:
    paths: Paths
    cfg: dict = field(default_factory=dict)
    device: Device = None

    @classmethod
    def load(cls, paths=None):
        paths = paths or Paths.default()
        cfg = config_mod.load(paths.config_file)
        ctx = cls(paths=paths, cfg=cfg, device=load_device(paths, cfg))
        migrate_state(ctx)
        return ctx

    @property
    def configured(self):
        return bool(self.cfg.get("providers"))


def migrate_state(ctx):
    """0.1.0-alpha kept one sync state at the top of the state folder; move it under the first provider. If that
    guess is wrong, the remote id check archives it and the provider is compared from scratch."""
    root = ctx.paths.state_dir
    first = next(iter(ctx.cfg.get("providers") or {}), None)
    if not first or not (root / "remote.json").exists():
        return
    dest = ctx.paths.for_provider(first).provider_dir
    if dest.exists():
        return
    dest.mkdir(parents=True)
    for name in ("base", "remote.json", "conflicts.json", "last-prune.json"):
        if (root / name).exists():
            shutil.move(str(root / name), str(dest / name))


def load_device(paths, cfg):
    data = read_json(paths.device_file, {}) or {}
    if not data.get("id"):
        data = {"id": uuid.uuid4().hex[:12]}
        write_json(paths.device_file, data)
    name = cfg.get("device_name") or socket.gethostname() or "device"
    return Device(id=data["id"], name=name)
