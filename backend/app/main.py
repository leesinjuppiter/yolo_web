import logging
import os
from asyncio import to_thread
from contextlib import asynccontextmanager
from threading import Event, Thread

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.api.datasets import router as dataset_router
from app.api.exchange import router as exchange_router
from app.core.database import engine
from app.dataset.analysis.reporting import compute_report
from app.dataset.analysis.worker import run_worker
from app.dataset.repository import Conflict, NotFound


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("WORKBENCH_ANALYSIS_WORKER", "1") == "0":
        yield
        return
    stop = Event()
    worker = Thread(target=run_worker, args=(stop, compute_report), name="dataset-analysis", daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        await to_thread(worker.join, 5)


app = FastAPI(title="检测系统工作台", lifespan=lifespan)
app.include_router(dataset_router)
app.include_router(exchange_router)
log = logging.getLogger(__name__)


@app.get("/api/health")
def health():
    with engine().connect() as connection:
        connection.execute(text("select 1"))
    return {"status": "ok"}


@app.exception_handler(NotFound)
def not_found(_request: Request, error: NotFound):
    return JSONResponse({"detail": str(error)}, status_code=404)


@app.exception_handler(Conflict)
def conflict(_request: Request, error: Conflict):
    return JSONResponse({"detail": str(error)}, status_code=409)


@app.exception_handler(IntegrityError)
def database_conflict(_request: Request, _error: IntegrityError):
    return JSONResponse({"detail": "记录发生冲突，请刷新后重试"}, status_code=409)


@app.exception_handler(OperationalError)
def database_unavailable(_request: Request, _error: OperationalError):
    log.warning("PostgreSQL 不可用")
    return JSONResponse({"detail": "PostgreSQL 不可用，请检查数据库服务"}, status_code=503)


@app.exception_handler(ValueError)
def invalid_request(_request: Request, error: ValueError):
    return JSONResponse({"detail": str(error)}, status_code=422)
