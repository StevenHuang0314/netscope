"""Turns polled flows into rows.

One pass is: upsert the devices we saw -> insert their flows -> recompute the
1-minute rollup buckets those flows touched. The whole pass runs in a single
transaction, so a crash mid-ingest can never leave flows without matching
rollup rows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from app.db import SessionLocal
from app.models import Device, Flow, FlowMinute
from app.sources.base import DataSource, FlowRecord

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    """What one poll actually wrote. Surfaced by /api/ingest/status."""

    flows: int = 0
    devices: int = 0
    buckets: int = 0
    duration_ms: int = 0
    finished_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def upsert_devices(db: Session, records: list[FlowRecord]) -> dict[str, int]:
    """Create a device the first time we see its MAC, refresh it after.

    Returns mac -> device id for every MAC in the batch. Identity is the MAC,
    not the IP: DHCP hands out new IPs, so keying on IP would invent a new
    device every lease renewal.
    """
    # Collapse the batch to one row per MAC. Postgres refuses an ON CONFLICT DO
    # UPDATE that touches the same row twice in one statement, and a single poll
    # normally carries many flows per device.
    latest: dict[str, FlowRecord] = {}
    earliest_ts: dict[str, datetime] = {}
    for record in records:
        if not record.src_mac:
            continue
        mac = record.src_mac.lower()
        seen = latest.get(mac)
        if seen is None or record.ts > seen.ts:
            latest[mac] = record
        if mac not in earliest_ts or record.ts < earliest_ts[mac]:
            earliest_ts[mac] = record.ts

    if not latest:
        return {}

    rows = [
        {
            "mac": mac,
            "ip": record.src_ip,
            "hostname": record.src_hostname,
            "first_seen": earliest_ts[mac],
            "last_seen": record.ts,
        }
        for mac, record in latest.items()
    ]

    stmt = pg_insert(Device).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Device.mac],
        set_={
            # Keep whatever we already knew if this batch didn't carry it.
            "ip": func.coalesce(stmt.excluded.ip, Device.ip),
            "hostname": func.coalesce(stmt.excluded.hostname, Device.hostname),
            # GREATEST, not plain assignment: an out-of-order or replayed batch
            # must never drag last_seen backwards. first_seen is deliberately
            # absent — it is written once, on insert.
            "last_seen": func.greatest(stmt.excluded.last_seen, Device.last_seen),
        },
    ).returning(Device.mac, Device.id)

    # RETURNING on DO UPDATE yields both the newly inserted and the touched rows,
    # so this one statement gives us the full mac -> id map.
    return {mac: device_id for mac, device_id in db.execute(stmt).all()}


def insert_flows(
    db: Session, records: list[FlowRecord], mac_to_id: dict[str, int]
) -> int:
    """Bulk-insert the batch. Flows with an unknown MAC are kept, unattributed."""
    if not records:
        return 0

    payload = [
        {
            "device_id": mac_to_id.get(r.src_mac.lower()) if r.src_mac else None,
            "src_ip": r.src_ip,
            "dst_ip": r.dst_ip,
            "src_port": r.src_port,
            "dst_port": r.dst_port,
            "protocol": r.protocol,
            "bytes": r.bytes,
            "packets": r.packets,
            "ts": r.ts,
        }
        for r in records
    ]
    db.execute(insert(Flow), payload)
    return len(payload)


def rollup_minutes(db: Session, window_start: datetime, window_end: datetime) -> int:
    """Recompute per-device 1-minute totals for every bucket in [start, end).

    Recomputed from `flows` rather than incremented in place. That costs one
    grouped scan of a narrow time slice and buys idempotency: re-running ingest
    over a window that was already processed produces identical numbers instead
    of doubling them.
    """
    bucket = func.date_trunc("minute", Flow.ts).label("bucket")
    source = (
        select(
            Flow.device_id,
            bucket,
            func.sum(Flow.bytes),
            func.sum(Flow.packets),
            func.count(),
        )
        .where(
            Flow.device_id.is_not(None),
            Flow.ts >= window_start,
            Flow.ts < window_end,
        )
        .group_by(Flow.device_id, bucket)
    )

    stmt = pg_insert(FlowMinute).from_select(
        ["device_id", "bucket", "bytes", "packets", "flow_count"], source
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_flow_minutes_device_bucket",
        set_={
            "bytes": stmt.excluded.bytes,
            "packets": stmt.excluded.packets,
            "flow_count": stmt.excluded.flow_count,
        },
    )
    # Count via RETURNING rather than .rowcount: the driver reports -1 for an
    # INSERT ... FROM SELECT, which would otherwise show up as "-1 buckets" in
    # the logs and the status endpoint. RETURNING emits one row per affected
    # bucket, whether it was inserted or updated by the conflict clause.
    return len(db.execute(stmt.returning(FlowMinute.id)).all())


def _window(records: list[FlowRecord]) -> tuple[datetime, datetime]:
    """Smallest [start, end) covering every minute bucket the batch touched."""
    timestamps = [r.ts for r in records]
    start = min(timestamps).replace(second=0, microsecond=0)
    end = max(timestamps).replace(second=0, microsecond=0) + timedelta(minutes=1)
    return start, end


def ingest_once(
    source: DataSource, session_factory: sessionmaker = SessionLocal
) -> IngestResult:
    """Poll the source once and write everything it returned."""
    started = datetime.now(timezone.utc)
    records = source.poll()

    if not records:
        log.debug("ingest: source returned no flows")
        return IngestResult(duration_ms=_elapsed_ms(started))

    with session_factory() as db:
        with db.begin():
            mac_to_id = upsert_devices(db, records)
            flow_count = insert_flows(db, records, mac_to_id)
            # The rollup aggregates the rows just inserted. Both statements are
            # Core-level and execute immediately on the same connection, so the
            # flows are already visible to this transaction's SELECT.
            window_start, window_end = _window(records)
            bucket_count = rollup_minutes(db, window_start, window_end)

    result = IngestResult(
        flows=flow_count,
        devices=len(mac_to_id),
        buckets=bucket_count,
        duration_ms=_elapsed_ms(started),
    )
    log.info(
        "ingest: %d flows, %d devices, %d buckets in %dms",
        result.flows,
        result.devices,
        result.buckets,
        result.duration_ms,
    )
    return result


def _elapsed_ms(since: datetime) -> int:
    return int((datetime.now(timezone.utc) - since).total_seconds() * 1000)


if __name__ == "__main__":  # pragma: no cover - developer convenience
    # `python -m app.ingest` runs a single pass and exits. Handy for filling the
    # database without leaving the API running.
    import argparse

    from app.sources.synthetic import SyntheticSource

    parser = argparse.ArgumentParser(description="Run one ingest pass.")
    parser.add_argument(
        "--passes", type=int, default=1, help="number of polls to run (default 1)"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    synthetic = SyntheticSource()
    for _ in range(args.passes):
        ingest_once(synthetic)
