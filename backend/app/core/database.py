from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import database_url


class Base(DeclarativeBase):
    pass


@lru_cache
def engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True, hide_parameters=True)


def get_db():
    with Session(engine()) as db:
        yield db
