import os
from functools import lru_cache
from pathlib import Path

from sqlalchemy.engine import URL, make_url


@lru_cache
def database_url() -> URL:
    value = os.environ.get("WORKBENCH_DATABASE_URL")
    if not value:
        raise RuntimeError("请设置 WORKBENCH_DATABASE_URL 指向 PostgreSQL")
    url = make_url(value)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("检测系统工作台只支持 PostgreSQL")
    if url.drivername == "postgresql":
        return url.set(drivername="postgresql+psycopg")
    return url


@lru_cache
def data_dir() -> Path:
    default = Path(__file__).resolve().parents[2] / "data"
    return Path(os.environ.get("WORKBENCH_DATA_DIR", default)).expanduser().resolve()
