"""One PostgreSQL listener per API process, shared by all SSE clients."""

import asyncio
import json
import logging
from threading import Event, Thread

import psycopg

from app.core.config import database_url
from app.training.devices import capabilities

log = logging.getLogger(__name__)


class ChangeFeed:
    def __init__(self):
        self.stop = Event()
        self.clients: set[asyncio.Queue] = set()
        self.ready = False
        self.loop = asyncio.get_running_loop()
        self.thread = Thread(target=self._listen, name="change-notifications", daemon=True)
        self.health_thread = Thread(target=self._watch_worker, name="worker-health", daemon=True)

    def start(self):
        self.thread.start()
        self.health_thread.start()

    async def close(self):
        self.stop.set()
        await asyncio.to_thread(self.thread.join, 7)
        await asyncio.to_thread(self.health_thread.join, 2)

    def publish(self, event: str, payload: dict):
        for queue in tuple(self.clients):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(("sync", {}))
            else:
                queue.put_nowait((event, payload))

    def _send(self, event: str, payload: dict):
        if not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.publish, event, payload)

    def _connection_state(self, ready: bool):
        self.ready = ready
        self._send("sync" if ready else "status", {} if ready else {"state": "reconnecting"})

    def _listen(self):
        while not self.stop.is_set():
            try:
                url = database_url().set(drivername="postgresql").render_as_string(hide_password=False)
                with psycopg.connect(url, autocommit=True, connect_timeout=5,
                                     application_name="vision-change-feed") as connection:
                    connection.execute("LISTEN workbench_changes")
                    self._connection_state(True)
                    while not self.stop.is_set():
                        for notification in connection.notifies(timeout=1):
                            payload = json.loads(notification.payload)
                            self._send("change", payload)
                            if self.stop.is_set():
                                break
            except (psycopg.Error, ValueError, RuntimeError):
                self._connection_state(False)
                log.warning("变化通知连接中断，正在重连")
                self.stop.wait(3)

    def _watch_worker(self):
        previous = None
        while not self.stop.is_set():
            current = capabilities()
            current["workerStatus"].pop("sampledAt", None)
            signature = json.dumps(current, sort_keys=True)
            if previous is not None and previous != signature:
                self._send("change", {"topic": "worker"})
            previous = signature
            self.stop.wait(5)

    async def stream(self):
        queue = asyncio.Queue(maxsize=128)
        self.clients.add(queue)
        try:
            yield "retry: 3000\n\n"
            yield self._encode("sync" if self.ready else "status",
                               {} if self.ready else {"state": "reconnecting"})
            while not self.stop.is_set():
                try:
                    event, payload = await asyncio.wait_for(queue.get(), timeout=15)
                    yield self._encode(event, payload)
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            self.clients.discard(queue)

    @staticmethod
    def _encode(event: str, payload: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
