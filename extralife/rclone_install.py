"""Download the official rclone build into ~/.local/share/extra-life/bin (no root, nothing piped into a shell).
The zip is checked against the SHA256SUMS file published next to it on downloads.rclone.org."""

import hashlib
import io
import os
import platform
import re
import urllib.request
import zipfile

from .backends.rclone import BUNDLED

BASE = "https://downloads.rclone.org"
ARCH = {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "arm-v7"}


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "extra-life"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def install(log=print):
    arch = ARCH.get(platform.machine())
    if not arch:
        raise RuntimeError(f"no rclone build for {platform.machine()}")
    version = _get(f"{BASE}/version.txt").decode().strip().split()[-1]      # "rclone v1.71.2" -> "v1.71.2"
    if not re.fullmatch(r"v\d+\.\d+\.\d+", version):
        raise RuntimeError(f"unexpected rclone version string: {version!r}")
    name = f"rclone-{version}-linux-{arch}.zip"
    log(f"downloading {name} from {BASE}")
    sums = _get(f"{BASE}/{version}/SHA256SUMS").decode()
    m = re.search(rf"^([0-9a-f]{{64}})\s+\*?{re.escape(name)}$", sums, re.M)
    if not m:
        raise RuntimeError(f"{name} is not listed in SHA256SUMS")
    blob = _get(f"{BASE}/{version}/{name}", timeout=300)
    if hashlib.sha256(blob).hexdigest() != m.group(1):
        raise RuntimeError("checksum mismatch; nothing installed")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        member = next(n for n in z.namelist() if n.endswith("/rclone"))
        data = z.read(member)
    BUNDLED.parent.mkdir(parents=True, exist_ok=True)
    tmp = BUNDLED.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.chmod(tmp, 0o755)
    os.replace(tmp, BUNDLED)
    log(f"rclone {version} installed at {BUNDLED} (checksum verified)")
    return str(BUNDLED)
