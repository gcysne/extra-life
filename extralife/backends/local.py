"""Local folder backend (SD card, USB drive, mounted network share). Files are copied with rsync when it is
installed (keeps modification times, writes through temp files), otherwise with Python."""

import os
import shutil
from pathlib import Path

from .base import Backend, BackendError, check_rel, run, run_stream, rsync_progress
from ..util import write_text_atomic


class LocalBackend(Backend):
    kind = "local"

    def __init__(self, path):
        if not path:
            raise BackendError("remote.path is not set")
        self.root = Path(os.path.expanduser(path))
        if self.root == Path(self.root.anchor) or self.root == Path.home():
            raise BackendError("remote.path must be a folder of its own, e.g. /run/media/<card>/ExtraLife")
        self.rsync = shutil.which("rsync")

    def describe(self):
        return f"folder {self.root}"

    def _p(self, rel):
        return self.root / check_rel(rel) if rel else self.root

    def check(self):
        if self.root.is_dir():
            return
        if not self.root.parent.is_dir():
            raise BackendError(f"{self.root.parent} not found (card or drive not mounted?)")
        try:
            self.root.mkdir()
        except OSError as e:
            raise BackendError(f"can't create {self.root}: {e}") from e

    def read_text(self, rel):
        try:
            return self._p(rel).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def write_text(self, rel, text):
        write_text_atomic(self._p(rel), text)

    def delete(self, rel):
        try:
            self._p(rel).unlink()
        except FileNotFoundError:
            pass

    def fetch_tree(self, rel, dest):
        src = self._p(rel)
        if src.is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True)

    def _copy_files(self, src_root, dst_root, files, progress=None):
        if not files:
            return
        src_root, dst_root = Path(src_root), Path(dst_root)
        dst_root.mkdir(parents=True, exist_ok=True)
        if self.rsync:
            listing = b"\0".join(f.encode() for f in files) + b"\0"
            cmd = [self.rsync, "-t", "--ignore-times", "--from0", "--files-from=-"]
            if progress:
                run_stream([*cmd, "--info=progress2", "--no-human-readable", "--", f"{src_root}/", f"{dst_root}/"],
                           input=listing, on_line=rsync_progress(progress))
            else:
                run([*cmd, "--", f"{src_root}/", f"{dst_root}/"], input=listing)
            return
        done = 0
        for i, f in enumerate(files, 1):
            dst = dst_root / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(f".extralife-tmp-{dst.name}")
            shutil.copy2(src_root / f, tmp)
            os.replace(tmp, dst)
            done += dst.stat().st_size
            if progress:
                progress(done, i)

    def upload(self, src_root, rel_dir, files, progress=None):
        self._copy_files(src_root, self._p(rel_dir), files, progress)

    def download(self, rel_dir, dest_root, files, progress=None):
        self._copy_files(self._p(rel_dir), dest_root, files, progress)

    def copy(self, src_dir, dst_dir, files):
        present = [f for f in files if (self._p(src_dir) / f).is_file()]
        self._copy_files(self._p(src_dir), self._p(dst_dir), present)

    def move(self, src_dir, dst_dir, files):
        for f in files:
            src, dst = self._p(src_dir) / f, self._p(dst_dir) / f
            if not src.is_file():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
            _prune_empty(src.parent, self._p(src_dir))

    def list_dirs(self, rel):
        p = self._p(rel)
        return sorted(d.name for d in p.iterdir() if d.is_dir()) if p.is_dir() else []

    def list_files(self, rel):
        base = self._p(rel)
        out = []
        for dirpath, _, names in os.walk(base):
            for n in names:
                full = os.path.join(dirpath, n)
                out.append((os.path.relpath(full, base).replace(os.sep, "/"), os.path.getsize(full)))
        return sorted(out)

    def purge(self, rel):
        shutil.rmtree(self._p(rel), ignore_errors=True)


def _prune_empty(folder, stop):
    folder, stop = Path(folder), Path(stop)
    while folder != stop and stop in folder.parents:
        try:
            folder.rmdir()
        except OSError:
            return
        folder = folder.parent
