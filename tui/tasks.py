"""Owned read-only tasks; execution is deliberately not cancellable by navigation."""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine


class BackgroundTasks:
    def __init__(self):
        self._tasks = {}
        self._owned = set()

    def start(self, name: str, coroutine: Coroutine):
        self.cancel(name)
        task = asyncio.create_task(coroutine)
        self._tasks[name] = task
        self._owned.add(task)
        task.add_done_callback(self._owned.discard)
        return task

    def cancel(self, name: str):
        task = self._tasks.pop(name, None)
        if task is not None and not task.done():
            task.cancel()

    def cancel_all(self):
        for name in tuple(self._tasks):
            self.cancel(name)

    async def close(self):
        self.cancel_all()
        if self._owned:
            await asyncio.gather(*tuple(self._owned), return_exceptions=True)
