import asyncio
from collections import defaultdict

from fastapi import WebSocket


class JobBroadcaster:
    """In-process pub/sub of job progress to any connected WebSocket clients.

    Single-api-process assumption (fine for a personal/small-team tool); if the
    api is ever scaled to multiple replicas this would need to move to Redis pub/sub.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, job_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._subscribers[job_id].add(ws)

    async def unsubscribe(self, job_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._subscribers[job_id].discard(ws)

    async def publish(self, job_id: str, payload: dict) -> None:
        async with self._lock:
            targets = list(self._subscribers.get(job_id, ()))
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:
                pass


broadcaster = JobBroadcaster()
