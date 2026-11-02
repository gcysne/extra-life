"""Backend interface. Every path is POSIX, relative to the remote root; file lists are relative to a folder.

Layout on the remote (see docs/architecture.md):
    extra-life.json                       format marker
    lock.json                             best-effort lock while a device syncs
    devices/<id>.json                     devices that use this remote
    manifests/<profile>/<set>.json        what the latest version of every file is
    data/<profile>/<set>/<file>           latest versions
    history/<stamp>_<device>/<profile>/<set>/<file>   versions replaced or deleted by that sync
"""

import os
import subprocess


class BackendError(Exception):
    pass


def check_rel(rel):
    parts = rel.split("/")
    if rel.startswith("/") or any(p in ("..",) for p in parts):
        raise BackendError(f"bad remote path: {rel}")
    return rel


def clean_env():
    """Environment for child processes. Decky's bundled Python leaks LD_LIBRARY_PATH; restore the original."""
    env = dict(os.environ)
    orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if orig:
        env["LD_LIBRARY_PATH"] = orig
    else:
        env.pop("LD_LIBRARY_PATH", None)
    return env


def run(cmd, input=None, timeout=600, ok=(0,)):
    try:
        p = subprocess.run(cmd, input=input, capture_output=True, timeout=timeout, env=clean_env())
    except FileNotFoundError as e:
        raise BackendError(f"{cmd[0]} not found") from e
    except subprocess.TimeoutExpired as e:
        raise BackendError(f"{os.path.basename(cmd[0])} timed out after {timeout}s") from e
    if p.returncode not in ok:
        msg = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise BackendError(f"{os.path.basename(cmd[0])} failed ({p.returncode}): {' | '.join(msg[-3:])}")
    return p


class Backend:
    kind = ""

    def describe(self):
        raise NotImplementedError

    def check(self):
        """Raise BackendError if the remote can't be reached; create the root folder if needed."""
        raise NotImplementedError

    def read_text(self, rel):
        """File contents, or None if it doesn't exist."""
        raise NotImplementedError

    def write_text(self, rel, text):
        raise NotImplementedError

    def delete(self, rel):
        """Delete one file; no error if missing."""
        raise NotImplementedError

    def fetch_tree(self, rel, dest):
        """Copy a remote folder into the local folder dest (missing remote folder = nothing)."""
        raise NotImplementedError

    def upload(self, src_root, rel_dir, files):
        raise NotImplementedError

    def download(self, rel_dir, dest_root, files):
        raise NotImplementedError

    def copy(self, src_dir, dst_dir, files):
        """Remote-side copy of files from one folder to another (keeps them in src_dir)."""
        raise NotImplementedError

    def move(self, src_dir, dst_dir, files):
        raise NotImplementedError

    def list_dirs(self, rel):
        """Names of the folders directly in rel ([] if missing)."""
        raise NotImplementedError

    def list_files(self, rel):
        """[(relative path under rel, size)] of every file below rel ([] if missing)."""
        raise NotImplementedError

    def purge(self, rel):
        """Delete a folder and everything in it."""
        raise NotImplementedError
