"""config.toml: load with defaults, change single keys, write back.

The file only holds top-level scalars, tables of scalars or string lists, and [providers.<id>] tables, so a tiny
writer is enough (comments are not preserved when the CLI or the plugin changes a value).
"""

import copy
import tomllib
from pathlib import Path

from .util import write_text_atomic

DEFAULTS = {
    "device_name": "",
    # Every connected storage provider; each sync runs against all of them. One table per provider id:
    #   type = "local" | "rsync-ssh" | "rclone"
    #   path = folder (local) or folder on the host (rsync-ssh); host = [user@]host (rsync-ssh)
    #   remote = "name:folder" (rclone); rclone_config = rclone.conf that holds the sign-in ("" = rclone's own)
    #   rclone = rclone binary; args = extra rclone or ssh arguments
    "providers": {},
    "sync": {
        "on_game_exit": True,
        "include_states": False,
        "propagate_deletes": True,
        "history_days": 30,
        "backup_days": 30,
        "wait_for_exit": 60,
    },
    "profiles": {
        "enabled": ["auto"],  # "auto" = every profile whose save folder exists on this device
        "disabled": [],
    },
    "vars": {},               # path variables, e.g. emudeck = "/run/media/deck/SD/Emulation"
}


class ConfigError(Exception):
    pass


def _merge(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


LEGACY_IDS = {"local": "local", "rsync-ssh": "ssh", "rclone": "rclone"}


def migrate(data):
    """0.1.0-alpha had one [remote] table; it becomes one provider."""
    old = data.pop("remote", None)
    if isinstance(old, dict) and old.get("type") and not data.get("providers"):
        kind = old["type"]
        keep = {"local": ("path",), "rsync-ssh": ("host", "path", "args"),
                "rclone": ("remote", "rclone", "args")}.get(kind, ())
        prov = {"type": kind, **{k: old[k] for k in keep if old.get(k)}}
        data["providers"] = {LEGACY_IDS.get(kind, "remote"): prov}
    return data


def load(path):
    cfg = copy.deepcopy(DEFAULTS)
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return cfg
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    return _merge(cfg, migrate(data))


def _value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def dumps(cfg):
    lines = ["# Extra Life settings. Docs: docs/configuration.md", ""]
    tables = []
    for k, v in cfg.items():
        if isinstance(v, dict):
            tables.append((k, v))
        else:
            lines.append(f"{k} = {_value(v)}")
    for name, table in tables:
        subs = [(k, v) for k, v in table.items() if isinstance(v, dict)]
        plain = [(k, v) for k, v in table.items() if not isinstance(v, dict)]
        if plain or not subs:
            lines += ["", f"[{name}]"]
            lines += [f"{k} = {_value(v)}" for k, v in plain]
        for sub, inner in subs:
            lines += ["", f"[{name}.{sub}]"]
            lines += [f"{k} = {_value(v)}" for k, v in inner.items() if not isinstance(v, dict)]
    return "\n".join(lines) + "\n"


def save(path, cfg):
    write_text_atomic(path, dumps(cfg))


def parse_value(text):
    low = text.strip().lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        return int(text)
    except ValueError:
        return text


def get_key(cfg, key):
    node = cfg
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            raise ConfigError(f"unknown setting: {key}")
        node = node[part]
    return node


def set_key(cfg, key, value):
    parts = key.split(".")
    node = cfg
    for part in parts[:-1]:
        node = node.setdefault(part, {})
        if not isinstance(node, dict):
            raise ConfigError(f"not a table: {key}")
    known = get_key(DEFAULTS, key) if parts[0] not in ("vars", "providers") else ""
    if isinstance(known, bool) and not isinstance(value, bool):
        raise ConfigError(f"{key} must be true or false")
    if isinstance(known, int) and not isinstance(known, bool) and not isinstance(value, int):
        raise ConfigError(f"{key} must be a number")
    if isinstance(known, list) and not isinstance(value, list):
        value = [v.strip() for v in str(value).split(",") if v.strip()]
    node[parts[-1]] = value
