"""Agent execution guardrails (blueprint §25 runtime budget policy).

A coder attempt must run under a wall-clock ceiling. A real LLM backend can
hang on a dead socket or a slow upstream for minutes; a factory that sits on
an unresponsive worker indefinitely is not operational. ``run_with_timeout``
executes the callable in a *daemon* worker thread so the orchestrator can
reclaim the attempt when the ceiling is exceeded.

V1 contract: the timeout is enforced at the boundary - the factory always
gets its answer back (a CoderTimeout) and the ledger records the burned
budget. The worker thread itself cannot be force-killed from Python; killing
a truly runaway worker or isolating it in a fresh process is a V2 concern.
Daemon threads never block interpreter shutdown, so neither pytest nor the
CLI can hang on a still-running attempt.
"""
from __future__ import annotations

import queue
import threading
from typing import Callable, TypeVar

T = TypeVar("T")


class CoderTimeout(Exception):
    """Raised when a coder attempt does not finish within its allowance."""

    def __init__(self, timeout_s: float):
        super().__init__(
            f"coder attempt exceeded its {timeout_s:.1f}s runtime allowance"
        )
        self.timeout_s = timeout_s


def run_with_timeout(fn: Callable[[], T], timeout_s: float) -> T:
    """Run ``fn`` to completion or raise :class:`CoderTimeout` if the worker
    takes longer than ``timeout_s`` seconds.

    On success returns ``fn()``; any exception raised by the worker is
    re-raised in the caller's thread.
    """
    if timeout_s <= 0:
        raise CoderTimeout(timeout_s)
    box: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)

    def _worker() -> None:
        try:
            box.put(("ok", fn()))
        except BaseException as exc:  # noqa: BLE001 - a worker must not die silently
            box.put(("err", exc))

    thread = threading.Thread(
        target=_worker, name="factory-coder", daemon=True
    )
    thread.start()
    try:
        status, payload = box.get(timeout=timeout_s)
    except queue.Empty:
        raise CoderTimeout(timeout_s) from None
    if status == "err":
        raise payload  # type: ignore[misc]
    return payload  # type: ignore[return-value]
