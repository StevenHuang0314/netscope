import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import config
from app.scheduler import IngestScheduler
from app.sources.base import DataSource
from app.sources.synthetic import SyntheticSource

# Uvicorn sets up handlers for its own loggers only; the root logger stays bare,
# so anything app code logs is dropped. Attach a handler at import time, before
# uvicorn instantiates the app.
logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)

log = logging.getLogger(__name__)

scheduler: IngestScheduler | None = None


def build_source() -> DataSource:
    if config.INGEST_SOURCE == "synthetic":
        return SyntheticSource()
    raise ValueError(f"unknown INGEST_SOURCE: {config.INGEST_SOURCE!r}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global scheduler

    if config.INGEST_ENABLED:
        scheduler = IngestScheduler(build_source(), config.INGEST_INTERVAL_SECONDS)
        await scheduler.start()
    else:
        log.info("ingest disabled (INGEST_ENABLED=false)")

    yield

    if scheduler is not None:
        await scheduler.stop()
        scheduler = None


app = FastAPI(title="NetScope API", lifespan=lifespan)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/ingest/status")
def ingest_status():
    """Is the collector alive, and what did it last write?"""
    if scheduler is None:
        return {"enabled": False, "running": False}
    return {"enabled": True, **scheduler.status.as_dict()}
