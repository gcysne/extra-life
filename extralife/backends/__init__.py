from .base import Backend, BackendError


def make_backend(cfg):
    r = cfg.get("remote", {})
    kind = r.get("type", "")
    args = list(r.get("args") or [])
    if kind == "local":
        from .local import LocalBackend
        return LocalBackend(r.get("path", ""))
    if kind == "rsync-ssh":
        from .rsync_ssh import RsyncSshBackend
        return RsyncSshBackend(r.get("host", ""), r.get("path", ""), args)
    if kind == "rclone":
        from .rclone import RcloneBackend
        return RcloneBackend(r.get("remote", ""), r.get("rclone", ""), args)
    if not kind:
        raise BackendError("no remote configured; run `extralife setup`")
    raise BackendError(f"unknown remote type: {kind} (local, rsync-ssh or rclone)")


__all__ = ["Backend", "BackendError", "make_backend"]
