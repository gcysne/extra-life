"""Where Extra Life keeps its files, and the per-run context (paths, config, this device)."""

import os
import socket
import uuid
from dataclasses import dataclass, field
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

    @classmethod
    def default(cls):
        cfg = os.environ.get("EXTRALIFE_CONFIG_DIR")
        state = os.environ.get("EXTRALIFE_STATE_DIR")
        return cls(Path(cfg) if cfg else _xdg("XDG_CONFIG_HOME", ".config") / APP_DIR,
                   Path(state) if state else _xdg("XDG_STATE_HOME", ".local/state") / APP_DIR)

    config_file = property(lambda s: s.config_dir / "config.toml")
    user_profiles = property(lambda s: s.config_dir / "profiles")
    base_dir = property(lambda s: s.state_dir / "base")            # remote manifests as of the last sync
    cache_dir = property(lambda s: s.state_dir / "hashcache")
    backup_dir = property(lambda s: s.state_dir / "backup")        # local files replaced or removed by a sync
    tmp_dir = property(lambda s: s.state_dir / "tmp")
    conflicts_file = property(lambda s: s.state_dir / "conflicts.json")
    last_run_file = property(lambda s: s.state_dir / "last-run.json")
    events_file = property(lambda s: s.state_dir / "events.jsonl")
    device_file = property(lambda s: s.state_dir / "device.json")
    lock_file = property(lambda s: s.state_dir / "lock")
    prune_file = property(lambda s: s.state_dir / "last-prune.json")
    remote_file = property(lambda s: s.state_dir / "remote.json")      # which remote the base belongs to


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
        return cls(paths=paths, cfg=cfg, device=load_device(paths, cfg))

    @property
    def configured(self):
        return bool(self.cfg["remote"].get("type"))


def load_device(paths, cfg):
    data = read_json(paths.device_file, {}) or {}
    if not data.get("id"):
        data = {"id": uuid.uuid4().hex[:12]}
        write_json(paths.device_file, data)
    name = cfg.get("device_name") or socket.gethostname() or "device"
    return Device(id=data["id"], name=name)
