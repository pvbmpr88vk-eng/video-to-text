"""macOS fork safety for RQ workers, ProcessPool STT, and ObjC runtimes."""

from __future__ import annotations

import os
import sys


def configure_fork_safety() -> None:
    """Call as early as possible in any process that may fork (worker, STT pool)."""
    if sys.platform != "darwin":
        return
    os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")
    try:
        import multiprocessing as mp

        mp.set_start_method("spawn", force=False)
    except RuntimeError:
        pass
