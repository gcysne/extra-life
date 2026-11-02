"""Save profiles: which folders of which emulator hold save games.

A profile is a TOML file (shipped in profiles/, or the user's own in ~/.config/extra-life/profiles/, which
override shipped ones with the same id). Each [[set]] is one folder synced as a unit; its `paths` are candidates,
the first that exists on this device wins (symlinks are resolved). See docs/profiles.md.
"""

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
GLOBAL_EXCLUDE = [".lock", "*.tmp", ".DS_Store", "Thumbs.db", "desktop.ini", ".extralife-*"]


class ProfileError(Exception):
    pass


@dataclass
class Profile:
    id: str
    name: str
    processes: list
    sets: list
    source: Path
    user: bool = False


@dataclass
class SyncSet:
    profile: str
    profile_name: str
    id: str
    kind: str                  # saves | states
    root: Path | None          # resolved folder on this device, None if not found
    include: list = field(default_factory=lambda: ["**"])
    exclude: list = field(default_factory=list)
    processes: list = field(default_factory=list)
    note: str = ""

    @property
    def key(self):
        return f"{self.profile}/{self.id}"


def _load_file(path, user):
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ProfileError(f"{path}: {e}") from e
    pid = data.get("id", "")
    if not ID_RE.match(pid):
        raise ProfileError(f"{path}: invalid or missing id")
    sets = data.get("set", [])
    if not sets:
        raise ProfileError(f"{path}: no [[set]] entries")
    for s in sets:
        if not ID_RE.match(s.get("id", "")) or not s.get("paths"):
            raise ProfileError(f"{path}: each [[set]] needs an id and paths")
        if s.get("kind", "saves") not in ("saves", "states"):
            raise ProfileError(f"{path}: kind must be saves or states")
    return Profile(id=pid, name=data.get("name", pid), processes=list(data.get("processes", [])),
                   sets=sets, source=path, user=user)


def load_profiles(paths, errors=None):
    """Return {id: Profile}; user profiles replace shipped ones. Bad files are reported in `errors`."""
    out = {}
    for folder, user in ((paths.shipped_profiles, False), (paths.user_profiles, True)):
        if not folder.is_dir():
            continue
        for f in sorted(folder.glob("*.toml")):
            try:
                p = _load_file(f, user)
            except ProfileError as e:
                if errors is not None:
                    errors.append(str(e))
                continue
            out[p.id] = p
    return out


def read_emudeck_settings(home=None):
    """EmuDeck keeps its folders in ~/.config/EmuDeck/settings.sh (KEY=value lines)."""
    f = Path(home or Path.home()) / ".config/EmuDeck/settings.sh"
    out = {}
    try:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r'^\s*(?:export\s+)?(\w+)=(["\']?)(.*?)\2\s*$', line)
            if m:
                out[m.group(1)] = m.group(3)
    except OSError:
        pass
    return out


def path_vars(cfg, home=None):
    home = str(home or Path.home())
    v = {"home": home}
    ed = read_emudeck_settings(home)
    if ed.get("emulationPath"):
        v["emudeck"] = ed["emulationPath"]
        v["emudeck_saves"] = ed.get("savesPath") or f"{ed['emulationPath']}/saves"
        v["emudeck_storage"] = ed.get("storagePath") or f"{ed['emulationPath']}/storage"
        v["emudeck_roms"] = ed.get("romsPath") or f"{ed['emulationPath']}/roms"
    v.update({k: str(x) for k, x in (cfg.get("vars") or {}).items()})
    return v


def expand(path, variables):
    """Expand ~ and {var}; None when a variable is unknown (e.g. no EmuDeck)."""
    try:
        text = path.format_map(_Strict(variables))
    except KeyError:
        return None
    if text.startswith("~"):
        text = variables["home"] + text[1:]
    return text


class _Strict(dict):
    def __missing__(self, key):
        raise KeyError(key)


def profile_enabled(profile, cfg, available):
    p = cfg.get("profiles", {})
    if profile.id in (p.get("disabled") or []):
        return False
    enabled = p.get("enabled") or []
    return profile.id in enabled or ("auto" in enabled and available)


def build_sets(profile, variables):
    sets = []
    for s in profile.sets:
        root = None
        for cand in s["paths"]:
            text = expand(cand, variables)
            if text and os.path.isdir(text):
                root = Path(os.path.realpath(text))
                break
        sets.append(SyncSet(profile=profile.id, profile_name=profile.name, id=s["id"],
                            kind=s.get("kind", "saves"), root=root,
                            include=list(s.get("include", ["**"])),
                            exclude=GLOBAL_EXCLUDE + list(s.get("exclude", [])),
                            processes=profile.processes, note=s.get("note", "")))
    return sets


def resolve(ctx, errors=None, only=None):
    """All sets to sync on this device: enabled profiles, existing folders, states only if wanted."""
    variables = path_vars(ctx.cfg)
    include_states = ctx.cfg["sync"].get("include_states", False)
    result, seen = [], {}
    for profile in load_profiles(ctx.paths, errors).values():
        if only and profile.id not in only:
            continue
        sets = build_sets(profile, variables)
        available = any(s.root for s in sets if s.kind == "saves")
        if not profile_enabled(profile, ctx.cfg, available):
            continue
        for s in sets:
            if s.root is None or (s.kind == "states" and not include_states):
                continue
            if s.root in seen:
                if errors is not None:
                    errors.append(f"{s.key}: same folder as {seen[s.root]}, skipped")
                continue
            seen[s.root] = s.key
            result.append(s)
    return result


def describe_all(ctx, errors=None):
    """Every profile with availability and enabled state (for `profiles` and the plugin)."""
    variables = path_vars(ctx.cfg)
    out = []
    for profile in load_profiles(ctx.paths, errors).values():
        sets = build_sets(profile, variables)
        available = any(s.root for s in sets if s.kind == "saves")
        out.append({
            "id": profile.id, "name": profile.name, "user": profile.user,
            "available": available, "enabled": profile_enabled(profile, ctx.cfg, available),
            "sets": [{"key": s.key, "kind": s.kind, "root": str(s.root) if s.root else None} for s in sets],
        })
    return sorted(out, key=lambda p: (not p["available"], p["name"].lower()))
