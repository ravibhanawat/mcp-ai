"""
Bridge a blocking token iterator into an async generator.

Provider SDKs and `requests` both stream synchronously. Iterating one directly
inside the FastAPI event loop blocks every other request on the worker, which is
why `agent/sap_agent.py` grew a hand-rolled queue-and-thread pattern around
Ollama. That pattern is correct; it just needed to live somewhere reusable so
each adapter does not reinvent it — and reinvent its bugs.

Exceptions raised in the worker thread are passed through the queue and re-raised
on the consuming side, so `async for` sees the same error the adapter would have
raised synchronously.
"""
from __future__ import annotations

import asyncio
import queue
import threading
from typing import AsyncIterator, Callable, Iterator

_SENTINEL = object()


async def iterate_in_thread(make_iterator: Callable[[], Iterator[str]]) -> AsyncIterator[str]:
    """Run `make_iterator()` on a worker thread, yielding its items asynchronously.

    `make_iterator` is a callable rather than an iterator so the HTTP request that
    produces it is also made off the event loop.
    """
    q: queue.Queue = queue.Queue()

    def _worker():
        try:
            for item in make_iterator():
                q.put(item)
        except BaseException as exc:      # noqa: BLE001 — re-raised on the consumer side
            q.put(exc)
        finally:
            q.put(_SENTINEL)

    threading.Thread(target=_worker, daemon=True).start()
    loop = asyncio.get_running_loop()
    while True:
        item = await loop.run_in_executor(None, q.get)
        if item is _SENTINEL:
            return
        if isinstance(item, BaseException):
            raise item
        yield item
