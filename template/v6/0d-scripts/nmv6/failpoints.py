"""Named deterministic crash points used by the mandatory recovery suite.

Failpoints are inert unless ``NM_V6_FAILPOINT`` exactly names the checkpoint.
Production callers must never set these variables.  Tests may choose a raised
exception or a real SIGKILL; only the latter is valid crash evidence.
"""

from __future__ import annotations

import os
import signal


FAILPOINT_ENV = "NM_V6_FAILPOINT"
FAILPOINT_ACTION_ENV = "NM_V6_FAILPOINT_ACTION"


class FailpointError(RuntimeError):
    """Controlled in-process fault used by narrow unit tests."""


def checkpoint(name: str) -> None:
    configured = os.environ.get(FAILPOINT_ENV)
    if configured != name:
        return
    action = os.environ.get(FAILPOINT_ACTION_ENV, "raise")
    if action == "raise":
        raise FailpointError(f"NM V6 failpoint reached: {name}")
    if action == "sigkill":
        os.kill(os.getpid(), signal.SIGKILL)
        raise AssertionError("SIGKILL unexpectedly returned")
    if action == "exit":
        os._exit(86)
    raise FailpointError(f"unsupported failpoint action {action!r} at {name}")


hit = checkpoint
