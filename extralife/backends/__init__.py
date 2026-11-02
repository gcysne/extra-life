from .base import Backend, BackendError


def make_backend(p):
    """Backend for one provider's settings (a [providers.<id>] table)."""
    kind = p.get("type", "")
    args = list(p.get("args") or [])
    if kind == "local":
        from .local import LocalBackend
        return LocalBackend(p.get("path", ""))
    if kind == "rsync-ssh":
        from .rsync_ssh import RsyncSshBackend
        return RsyncSshBackend(p.get("host", ""), p.get("path", ""), args)
    if kind == "rclone":
        from .rclone import RcloneBackend
        return RcloneBackend(p.get("remote", ""), p.get("rclone", ""), args, p.get("rclone_config", ""))
    if not kind:
        raise BackendError("provider has no type")
    raise BackendError(f"unknown provider type: {kind} (local, rsync-ssh or rclone)")


__all__ = ["Backend", "BackendError", "make_backend"]
