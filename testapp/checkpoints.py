"""
Checkpoints let the ETag concurrency tests pause a thread in the middle of
serializing a resource, so other threads can run in between.

Any way of maintaining ETags serializes a resource to compute its ETag, and a GET
serializes it for the body. A checkpoint before the reads of a serialization
pauses a GET between what it read before, like a stored ETag, and the body. A
checkpoint after the reads pauses a computation before its result is stored or
served, wherever it runs.
"""

import threading
from dataclasses import dataclass, field

GATE_TIMEOUT = 60  # seconds a paused thread waits before giving up


@dataclass
class Gate:
    """Pauses a thread at a checkpoint, after it passed ``skip`` others, until opened."""

    skip: int = 0
    reached: threading.Event = field(default_factory=threading.Event)
    opened: threading.Event = field(default_factory=threading.Event)


_armed: dict[int, Gate] = {}
_lock = threading.Lock()


def arm(thread_id: int, skip: int = 0) -> Gate:
    """Pause the thread ``thread_id`` at the checkpoint after the next ``skip``."""
    gate = Gate(skip)
    with _lock:
        _armed[thread_id] = gate
    return gate


def disarm(thread_id: int) -> None:
    """Forget a gate the thread ``thread_id`` never reached."""
    with _lock:
        _armed.pop(thread_id, None)


def checkpoint() -> None:
    """Wait here if a gate is armed for the current thread and nothing to skip."""
    with _lock:
        gate = _armed.get(thread_id := threading.get_ident())
        if gate is None:
            return
        if gate.skip:
            gate.skip -= 1
            return
        del _armed[thread_id]
    gate.reached.set()
    if not gate.opened.wait(timeout=GATE_TIMEOUT):
        raise RuntimeError("A paused serialization was never resumed")
