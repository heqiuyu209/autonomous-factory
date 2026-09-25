"""Agent execution guardrails (blueprint §25 runtime budget policy).

A coder attempt must run under a wall-clock ceiling. A real LLM backend can
hang on a dead socket or a slow upstream for minutes; a factory that sits on
an unresponsive worker indefinitely is not operational.

Two enforcement levels:

- ``run_with_timeout`` (thread-level): executes the callable in a daemon
  worker thread and returns after the ceiling. The factory always gets its
  answer back (a :class:`CoderTimeout`) and the ledger records the burned
  budget. A worker thread cannot be force-killed from Python, so a runaway
  worker keeps running in the background; use this only for cheap, side-effect
  free callables (tests, trivial helpers).

- ``run_with_timeout_isolated`` (process-level): executes the callable in a
  fresh spawned process and *hard-kills* it on timeout via
  ``Process.terminate()``. This is the production path for real LLM backends:
  a hung attempt cannot keep writing files, burning CPU or holding sockets
  after the factory has reclaimed it. The callable (and everything it closes
  over) must be picklable; if not, a clear :class:`TypeError` is raised
  instead of silently degrading.
"""
from __future__ import annotations

import multiprocessing
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
    re-raised in the caller's thread. This is the *thread-level* guard: the
    worker itself is NOT hard-killed on timeout (Python threads cannot be
    killed), so prefer :func:`run_with_timeout_isolated` for anything with
    real side effects.
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


def _mp_worker(box: multiprocessing.Queue, fn: Callable[[], T]) -> None:
    """Top-level spawn target; ``fn`` must be picklable."""
    try:
        box.put(("ok", fn()))
    except BaseException as exc:  # noqa: BLE001 - a worker must not die silently
        box.put(("err", exc))


def run_with_timeout_isolated(fn: Callable[[], T], timeout_s: float) -> T:
    """Process-isolated variant: run ``fn`` in a spawned process and hard-kill
    it when the ceiling is exceeded.

    On success returns ``fn()``; any exception raised by the worker is
    re-raised in the caller's process. On timeout the worker process is
    terminated before :class:`CoderTimeout` is raised, so no side effects
    survive the reclaim.

    ``fn`` and everything it closes over must be picklable (module-level
    functions / ``functools.partial`` with picklable args). Unpicklable
    targets raise :class:`TypeError` at spawn time.
    """
    if timeout_s <= 0:
        raise CoderTimeout(timeout_s)
    ctx = multiprocessing.get_context("spawn")
    box = ctx.Queue(maxsize=1)
    proc = ctx.Process(target=_mp_worker, args=(box, fn), daemon=True)
    proc.start()
    try:
        proc.join(timeout_s)
        if proc.is_alive():
            proc.terminate()
            proc.join()
            raise CoderTimeout(timeout_s)
    except BaseException:
        if proc.is_alive():
            proc.terminate()
            proc.join()
        raise
    status, payload = box.get(timeout=1.0)
    if status == "err":
        raise payload  # type: ignore[misc]
    return payload  # type: ignore[return-value]
