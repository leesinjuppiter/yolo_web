"""Per-device execution slots shared by training and recommendation workers."""
from collections.abc import Callable
from contextlib import contextmanager
from time import sleep

from sqlalchemy import text

from app.core.database import engine


@contextmanager
def device_slot(device_id: str, check: Callable[[], None], waiting: Callable[[], None] | None = None):
    if not device_id.startswith("cuda:"):
        yield
        return
    key = 154026222000 + int(device_id.split(":")[1])
    with engine().connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        notified = False
        while not connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}):
            check()
            if waiting and not notified:
                waiting()
                notified = True
            sleep(0.25)
        try:
            check()
            yield
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
