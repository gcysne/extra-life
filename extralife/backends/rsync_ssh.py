"""rsync over SSH to a NAS or another computer. Needs key-based ssh login (BatchMode, no password prompts) and
rsync, sh, find and stat on the host. Status: written against POSIX tools, not yet tested on real hardware."""

import shlex
import shutil

from .base import Backend, BackendError, check_rel, run, run_stream, rsync_progress

NOT_FOUND = 44


class RsyncSshBackend(Backend):
    kind = "rsync-ssh"

    def __init__(self, host, path, args=()):
        if not host or not path:
            raise BackendError("remote.host and remote.path must be set")
        self.host, self.root = host, path.rstrip("/")
        self.ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", *args]
        self.rsync = shutil.which("rsync") or "rsync"

    def describe(self):
        return f"{self.host}:{self.root} (rsync over ssh)"

    def _p(self, rel):
        return f"{self.root}/{check_rel(rel)}" if rel else self.root

    def _sh(self, script, input=None, ok=(0,)):
        return run([*self.ssh, self.host, "sh", "-c", shlex.quote(script)], input=input, ok=ok)

    def _rsync(self, src, dst, files, progress=None):
        listing = b"\0".join(f.encode() for f in files) + b"\0"
        cmd = [self.rsync, "-t", "--ignore-times", "--from0", "--files-from=-", "-e", shlex.join(self.ssh)]
        if progress:
            run_stream([*cmd, "--info=progress2", "--no-human-readable", "--", src, dst], input=listing,
                       on_line=rsync_progress(progress))
        else:
            run([*cmd, "--", src, dst], input=listing)

    def check(self):
        self._sh(f"mkdir -p {shlex.quote(self.root)}")

    def read_text(self, rel):
        p = shlex.quote(self._p(rel))
        r = self._sh(f"test -f {p} || exit {NOT_FOUND}; cat {p}", ok=(0, NOT_FOUND))
        return None if r.returncode == NOT_FOUND else r.stdout.decode("utf-8")

    def write_text(self, rel, text):
        p = self._p(rel)
        q, tmp = shlex.quote(p), shlex.quote(p + ".extralife-tmp")
        d = shlex.quote(p.rsplit("/", 1)[0])
        self._sh(f"mkdir -p {d} && cat > {tmp} && mv -f {tmp} {q}", input=text.encode("utf-8"))

    def delete(self, rel):
        self._sh(f"rm -f {shlex.quote(self._p(rel))}")

    def fetch_tree(self, rel, dest):
        p = shlex.quote(self._p(rel))
        if self._sh(f"test -d {p} || exit {NOT_FOUND}", ok=(0, NOT_FOUND)).returncode == NOT_FOUND:
            return
        dest.mkdir(parents=True, exist_ok=True)
        run([self.rsync, "-rt", "-e", shlex.join(self.ssh), "--", f"{self.host}:{self._p(rel)}/", f"{dest}/"])

    def upload(self, src_root, rel_dir, files, progress=None):
        if files:
            self._sh(f"mkdir -p {shlex.quote(self._p(rel_dir))}")
            self._rsync(f"{src_root}/", f"{self.host}:{self._p(rel_dir)}/", files, progress)

    def download(self, rel_dir, dest_root, files, progress=None):
        if files:
            dest_root.mkdir(parents=True, exist_ok=True)
            self._rsync(f"{self.host}:{self._p(rel_dir)}/", f"{dest_root}/", files, progress)

    def _each(self, verb, src_dir, dst_dir, files):
        lines = []
        for f in files:
            s, d = shlex.quote(f"{self._p(src_dir)}/{f}"), f"{self._p(dst_dir)}/{f}"
            lines.append(f"if [ -f {s} ]; then mkdir -p {shlex.quote(d.rsplit('/', 1)[0])} && "
                         f"{verb} {s} {shlex.quote(d)} || exit 1; fi")
        if lines:
            self._sh("\n".join(lines))

    def copy(self, src_dir, dst_dir, files):
        self._each("cp -p", src_dir, dst_dir, files)

    def move(self, src_dir, dst_dir, files):
        self._each("mv -f", src_dir, dst_dir, files)

    def list_dirs(self, rel):
        p = self._p(rel)
        r = self._sh(f"cd {shlex.quote(p)} 2>/dev/null || exit 0; for d in */; do [ -d \"$d\" ] && echo \"${{d%/}}\"; "
                     "done; exit 0")
        return sorted(x for x in r.stdout.decode("utf-8").splitlines() if x)

    def list_files(self, rel):
        p = self._p(rel)
        r = self._sh(f"cd {shlex.quote(p)} 2>/dev/null || exit 0; find . -type f -exec stat -c '%s %n' {{}} +")
        out = []
        for line in r.stdout.decode("utf-8").splitlines():
            size, _, name = line.partition(" ")
            if name.startswith("./"):
                out.append((name[2:], int(size)))
        return sorted(out)

    def purge(self, rel):
        if not rel:
            raise BackendError("refusing to purge the remote root")
        self._sh(f"rm -rf {shlex.quote(self._p(rel))}")
