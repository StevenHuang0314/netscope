"""Background loop that calls ingest on a fixed interval.

Deliberately plain asyncio rather than Celery/APScheduler: one process, one
task, no broker to run. The database work is synchronous SQLAlchemy, so each
pass is handed to a worker thread and never blocks the event loop serving the
API.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from app.ingest import IngestResult, ingest_once
from app.sources.base import DataSource

log = logging.getLogger(__name__)

# After repeated failures, stop hammering a database that is clearly down.
MAX_BACKOFF_SECONDS = 120


@dataclass
class SchedulerStatus:
    running: bool = False
    interval_seconds: int = 0
    passes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    flows_written: int = 0
    last_run_at: datetime | None = None
    last_duration_ms: int | None = None
    last_error: str | None = None

    def as_dict(self) -> dict:
        data = asdict(self)
        data["last_run_at"] = (
            self.last_run_at.isoformat() if self.last_run_at else None
        )
        return data


class IngestScheduler:
    def __init__(self, source: DataSource, interval_seconds: int) -> None:
        self._source = source
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self.status = SchedulerStatus(interval_seconds=interval_seconds)

    async def start(self) -> None:
        if self._task is not None:
            return
        self.status.running = True
        self._task = asyncio.create_task(self._run(), name="ingest-loop")
        log.info("ingest scheduler started (every %ss)", self._interval)

    async def stop(self) -> None:
        self.status.running = False
        if self._task is None:
            return
        self._task.cancel()
        # Wait for the in-flight pass to unwind so shutdown doesn't race a
        # half-open database session.
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        log.info("ingest scheduler stopped")

    async def _run(self) -> None:
        # Run immediately on boot, then on the interval, so a fresh database has
        # data before the first minute is up.
        while True:
            try:
                result = await asyncio.to_thread(ingest_once, self._source)
                self._record_success(result)
                delay = self._interval
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the loop must survive anything
                self._record_failure(exc)
                delay = self._backoff()
                log.exception("ingest pass failed; retrying in %ss", delay)
            await asyncio.sleep(delay)

    def _record_success(self, result: IngestResult) -> None:
        self.status.passes += 1
        self.status.consecutive_failures = 0
        self.status.flows_written += result.flows
        self.status.last_run_at = result.finished_at
        self.status.last_duration_ms = result.duration_ms
        self.status.last_error = None

    def _record_failure(self, exc: Exception) -> None:
        self.status.failures += 1
        self.status.consecutive_failures += 1
        self.status.last_run_at = datetime.now(timezone.utc)
        self.status.last_error = f"{type(exc).__name__}: {exc}"

    def _backoff(self) -> int:
        """Exponential, capped — a database restart shouldn't spam the log."""
        return min(
            MAX_BACKOFF_SECONDS,
            self._interval * (2 ** min(self.status.consecutive_failures - 1, 5)),
        )
