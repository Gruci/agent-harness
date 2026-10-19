"""Process locks for task registration and landing, shared by linked Git worktrees.

The lock files stay in the common Git directory. Ownership belongs to the operating
system, so an interrupted process releases its lock without deleting a file that
another process may already have opened. These locks coordinate one local clone;
different machines still require the remote integration policy.
"""

from __future__ import annotations

import errno
import hashlib
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

from kernel.context import git_common_dir

if os.name == "nt":
    import msvcrt
else:
    import fcntl

CONTENDED = (errno.EACCES, errno.EAGAIN, errno.EDEADLK)


def _file_lock(handle: BinaryIO, acquire: bool) -> None:
    """Lock one stable byte on Windows, or the open file description on POSIX."""
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB if acquire else fcntl.LOCK_UN)


@contextmanager
def task_lock(root: Path, name: str, timeout: float = 30) -> Iterator[None]:
    """Acquire a non-reentrant named lock, or raise TimeoutError without changing task state.

    Use the same name, such as ``scope:<scope>`` or ``land``, from every caller of
    the protected operation. Git lookup and filesystem errors propagate to the
    caller rather than silently running an unlocked operation.
    """
    if timeout < 0:
        raise ValueError("task lock timeout must be nonnegative")
    common = git_common_dir(root)
    if common is None:
        raise OSError(f"cannot locate the shared Git directory for {root}")
    folder = common / "harness-task-locks"
    folder.mkdir(exist_ok=True)
    path = folder / (hashlib.sha256(name.encode("utf-8")).hexdigest() + ".lock")
    deadline = time.monotonic() + timeout
    with path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        while True:
            try:
                _file_lock(handle, True)
                break
            except OSError as exc:
                if exc.errno not in CONTENDED:
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"timed out waiting for task lock {name!r}") from exc
                time.sleep(min(0.05, remaining))
        try:
            yield
        finally:
            _file_lock(handle, False)
