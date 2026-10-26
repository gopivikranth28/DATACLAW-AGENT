"""Owner-only, atomic file writes for files that hold credentials."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def write_private_text(path: Path, text: str) -> None:
    """Atomically replace ``path`` with ``text``, readable only by the owner.

    The content goes to a temp file in the same directory (created 0600 by
    ``mkstemp``) and is then renamed over the target, so a crash mid-write
    never leaves a truncated config and the secret is never briefly
    world-readable. A symlinked target is written through to the real file.
    """
    target = Path(os.path.realpath(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def restrict_permissions(path: Path) -> None:
    """Best-effort chmod 0600 for an existing secrets file written by older versions."""
    with contextlib.suppress(OSError):
        if path.is_file() and path.stat().st_mode & 0o077:
            path.chmod(0o600)
