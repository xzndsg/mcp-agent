"""async generator -> 同步 generator 的桥接。

Flask 是 WSGI（同步）应用，而 Agent 的流式输出是 async generator。
在守护线程中跑独立事件循环，通过 queue.Queue 把事件转给 Flask 的同步生成器
（SSE 响应与 flask-sock 的同步 WebSocket 均使用此桥接）。
"""
from __future__ import annotations

import asyncio
import queue
import threading
from typing import Any, AsyncGenerator, Generator


def async_gen_to_sync(agen: AsyncGenerator[Any, None]) -> Generator[Any, None, None]:
    queue_: queue.Queue = queue.Queue(maxsize=256)
    sentinel = object()

    async def _pump() -> None:
        async for item in agen:
            queue_.put(item)

    def _run() -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_pump())
        except BaseException as exc:  # noqa: BLE001 - 传到消费侧抛出
            queue_.put(exc)
        finally:
            queue_.put(sentinel)
            loop.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    while True:
        item = queue_.get()
        if item is sentinel:
            break
        if isinstance(item, BaseException):
            raise item
        yield item
