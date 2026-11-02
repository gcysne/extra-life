"""rclone backend: one implementation for every cloud rclone supports (Google Drive, Dropbox, OneDrive, S3,
WebDAV/Nextcloud, SFTP...). The rclone remote itself is set up once with `rclone config` (see docs/backends.md).
Copies and moves inside the remote are server-side where the provider allows it."""

import json
import os
import shutil
from pathlib import Path

from .base import Backend, BackendError, check_rel, run

# rclone exit codes: 3 = directory not found, 4 = file not found
MISSING = (3, 4)
BUNDLED = Path.home() / ".local/share/extra-life/bin/rclone"


def find_rclone(configured=""):
    for cand in (configured, str(BUNDLED), shutil.which("rclone")):
        if cand and os.access(os.path.expanduser(cand), os.X_OK):
            return os.path.expanduser(cand)
    return None


class RcloneBackend(Backend):
    kind = "rclone"

    def __init__(self, remote, binary="", args=()):
        if not remote or ":" not in remote:
            raise BackendError("remote.remote must look like name:folder (e.g. gdrive:ExtraLife)")
        if not remote.rpartition(":")[2].strip("/"):
            # Never write into the root of someone's cloud storage: everything goes in one folder.
            raise BackendError(f"give a folder after the remote name, e.g. {remote.rstrip(':/')}:ExtraLife")
        self.remote = remote
        self.bin = find_rclone(binary)
        if not self.bin:
            raise BackendError("rclone not found; run `extralife install-rclone`")
        self.flags = ["--retries", "3", "--low-level-retries", "10", "--log-level", "ERROR", *args]

    def describe(self):
        return f"rclone {self.remote}"

    def _p(self, rel):
        if not rel:
            return self.remote
        rel = check_rel(rel)
        return f"{self.remote}{rel}" if self.remote.endswith(":") else f"{self.remote.rstrip('/')}/{rel}"

    def _rc(self, *args, input=None, ok=(0,), timeout=900):
        return run([self.bin, *args, *self.flags], input=input, ok=ok, timeout=timeout)

    def check(self):
        r = self._rc("lsf", "--max-depth", "1", self._p(""), ok=(0, *MISSING), timeout=120)
        if r.returncode in MISSING:
            self._rc("mkdir", self._p(""), timeout=120)

    def read_text(self, rel):
        r = self._rc("cat", self._p(rel), ok=(0, *MISSING), timeout=120)
        if r.returncode in MISSING:
            return None
        return r.stdout.decode("utf-8")

    def write_text(self, rel, text):
        self._rc("rcat", self._p(rel), input=text.encode("utf-8"), timeout=120)

    def delete(self, rel):
        self._rc("deletefile", self._p(rel), ok=(0, *MISSING), timeout=120)

    def fetch_tree(self, rel, dest):
        Path(dest).mkdir(parents=True, exist_ok=True)
        self._rc("copy", self._p(rel), str(dest), ok=(0, *MISSING))

    def _list(self, files):
        return ("\n".join(files) + "\n").encode("utf-8")

    def upload(self, src_root, rel_dir, files):
        if files:
            self._rc("copy", str(src_root), self._p(rel_dir), "--files-from-raw", "-", "--no-traverse", "--ignore-times",
                     input=self._list(files))

    def download(self, rel_dir, dest_root, files):
        if files:
            Path(dest_root).mkdir(parents=True, exist_ok=True)
            self._rc("copy", self._p(rel_dir), str(dest_root), "--files-from-raw", "-", "--no-traverse", "--ignore-times",
                     input=self._list(files))

    def copy(self, src_dir, dst_dir, files):
        if files:
            self._rc("copy", self._p(src_dir), self._p(dst_dir), "--files-from-raw", "-", "--no-traverse", "--ignore-times",
                     input=self._list(files), ok=(0, *MISSING))

    def move(self, src_dir, dst_dir, files):
        if files:
            self._rc("move", self._p(src_dir), self._p(dst_dir), "--files-from-raw", "-", "--no-traverse", "--ignore-times",
                     input=self._list(files), ok=(0, *MISSING))

    def list_dirs(self, rel):
        r = self._rc("lsf", "--dirs-only", self._p(rel), ok=(0, *MISSING), timeout=120)
        if r.returncode in MISSING:
            return []
        return sorted(x.rstrip("/") for x in r.stdout.decode("utf-8").splitlines() if x)

    def list_files(self, rel):
        r = self._rc("lsjson", "-R", "--files-only", "--no-mimetype", self._p(rel), ok=(0, *MISSING),
                     timeout=300)
        if r.returncode in MISSING:
            return []
        return sorted((e["Path"], int(e.get("Size", 0))) for e in json.loads(r.stdout or b"[]"))

    def purge(self, rel):
        if not rel:
            raise BackendError("refusing to purge the remote root")
        self._rc("purge", self._p(rel), ok=(0, *MISSING))
