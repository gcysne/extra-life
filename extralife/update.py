"""Is there a newer Extra Life release on GitHub? Checked at most every CHECK_HOURS; the answer is cached.

Extra Life isn't in the Decky store, so Decky never offers updates for it: the plugin's About tab uses this check
and tells the user how to update (RELEASE_INSTALL in Desktop Mode)."""

import json
import urllib.error
import urllib.request
from datetime import timedelta

from . import __version__
from .util import is_newer, iso, parse_iso, read_json, utcnow, write_json

REPO = "gcysne/extra-life"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASE_INSTALL = f"curl -fsSL https://github.com/{REPO}/releases/latest/download/get-release.sh | bash"
CHECK_HOURS = 12


def _fetch(timeout=15):
    req = urllib.request.Request(API, headers={"User-Agent": f"extra-life/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def check(paths, force=False, fetch=_fetch):
    cache_file = paths.state_dir / "update-check.json"
    cached = read_json(cache_file, {}) or {}
    last = parse_iso(cached.get("checked"))
    fresh = last and utcnow() - last < timedelta(hours=CHECK_HOURS)
    if force or not fresh or cached.get("current") != __version__:
        cached = {"checked": iso(), "current": __version__}
        try:
            rel = fetch()
            cached.update(latest=str(rel.get("tag_name", "")).lstrip("vV"), url=rel.get("html_url", ""),
                          published=rel.get("published_at", ""), notes=(rel.get("body") or "")[:1500])
        except urllib.error.HTTPError as e:
            cached["error"] = "no release published yet" if e.code == 404 else f"GitHub answered {e.code}"
        except (urllib.error.URLError, OSError, ValueError) as e:
            cached["error"] = f"couldn't reach GitHub ({getattr(e, 'reason', e)})"
        try:
            write_json(cache_file, cached)
        except OSError:
            pass
    out = dict(cached)
    out["current"] = __version__
    out["newer"] = bool(out.get("latest")) and is_newer(out["latest"], __version__)
    out["command"] = RELEASE_INSTALL
    return out
