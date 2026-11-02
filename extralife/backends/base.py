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
import threading


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


def run_stream(cmd, input=None, timeout=900, ok=(0,), on_line=None, split=b"\n"):
    """Like run(), but hands every output line (stdout and stderr, split on newlines or carriage returns) to
    on_line(text) while the command runs; used for transfer progress. Returns the exit code."""
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=clean_env())
    except FileNotFoundError as e:
        raise BackendError(f"{cmd[0]} not found") from e
    tail = []

    def pump(stream, keep):
        buf = b""
        while True:
            chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(4096)
            if not chunk:
                break
            buf += chunk.replace(b"\r", b"\n")
            *lines, buf = buf.split(b"\n")
            for raw in lines:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                handled = False
                if on_line:
                    try:
                        handled = on_line(line)
                    except Exception:     # progress is cosmetic; never fail a transfer over it
                        pass
                if keep and not handled:
                    tail.append(line)
                    del tail[:-3]

    threads = [threading.Thread(target=pump, args=(p.stdout, False), daemon=True),
               threading.Thread(target=pump, args=(p.stderr, True), daemon=True)]
    for t in threads:
        t.start()
    try:
        if input:
            p.stdin.write(input)
        p.stdin.close()
    except BrokenPipeError:
        pass
    try:
        p.wait(timeout)
    except subprocess.TimeoutExpired as e:
        p.kill()
        p.wait()
        raise BackendError(f"{os.path.basename(cmd[0])} timed out after {timeout}s") from e
    for t in threads:
        t.join(5)
    p.stdout.close()
    p.stderr.close()
    if p.returncode not in ok:
        raise BackendError(f"{os.path.basename(cmd[0])} failed ({p.returncode}): {' | '.join(tail[-3:])}")
    return p.returncode


def rsync_progress(progress):
    """Line handler for rsync --info=progress2 --no-human-readable: "  1234567  45%  1.2MB/s  0:00:01 (xfr#3, ...)"."""
    import re
    pat = re.compile(r"^(\d+)\s+\d+%(?:.*xfr#(\d+))?")

    def on_line(line):
        m = pat.match(line)
        if not m:
            return False
        progress(int(m.group(1)), int(m.group(2) or 0))
        return True
    return on_line


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

    def upload(self, src_root, rel_dir, files, progress=None):
        """progress(bytes_done, files_done) may be called while it runs (both counted from the start of this call)."""
        raise NotImplementedError

    def download(self, rel_dir, dest_root, files, progress=None):
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
