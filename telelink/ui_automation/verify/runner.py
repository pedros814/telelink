"""Generic polling helper for UI verification."""

from __future__ import annotations

import time
from typing import Callable

VerifyProbe = Callable[[], tuple[bool, str]]


def run_verify(fn: VerifyProbe, timeout_ms: int, poll_ms: int) -> tuple[bool, str]:
    """
    Poll fn() until success, terminal failure, or timeout.

    The probe should return:
    - (True, "<method>") for success
    - (False, "pending") for keep polling
    - (False, "<reason>") for terminal failure
    """
    poll_s = max(0.15, int(poll_ms) / 1000.0)
    deadline = time.monotonic() + max(0.5, int(timeout_ms) / 1000.0)
    last_reason = "timeout"

    while time.monotonic() < deadline:
        ok, method = fn()
        method = method or "pending"
        if ok:
            return True, method
        if method != "pending":
            return False, method
        time.sleep(poll_s)
        last_reason = "timeout"

    ok, method = fn()
    method = method or "pending"
    if ok:
        return True, method
    if method != "pending":
        return False, method
    return False, last_reason
