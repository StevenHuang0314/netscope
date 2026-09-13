"""Read queries over the rollup table.

These are written as parameterised raw SQL rather than ORM expressions. Two
reasons: reporting queries built from generate_series, LEFT JOIN gap-fills and
window functions read far more clearly as SQL than as a Core expression tree,
and the SQL here is exactly what was executed and verified against Postgres.
Every value is bound, never interpolated.

Everything reads `flow_minutes`, never `flows` — that is the point of keeping a
rollup table. Charting a day of traffic touches ~1440 rows per device instead of
every flow ever recorded.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

BUCKET_SECONDS = 60

# A device counts as active if it was heard from within this many minutes.
ACTIVE_WITHIN_MINUTES = 5


def window_bounds(minutes: int) -> tuple[datetime, datetime]:
    """The inclusive [start, end] minute-aligned window ending at the current minute.

    Inclusive at both ends, so `minutes=60` yields exactly 60 buckets. The end is
    truncated to the current minute rather than "now": the in-progress minute is
    still filling, and showing a partial bucket makes the last point of every
    chart dip toward zero for reasons that have nothing to do with the network.
    """
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(minutes=minutes - 1)
    return start, end


_SERIES_SQL = text(
    """
    WITH bucket_grid AS (
        SELECT generate_series(
            CAST(:start AS timestamptz),
            CAST(:end AS timestamptz),
            INTERVAL '1 minute'
        ) AS bucket
    ),
    included AS (
        -- Devices that actually have traffic in this window. A device idle for
        -- the whole window is left out entirely rather than drawn as a flat
        -- zero line nobody asked for.
        SELECT d.id, d.mac, d.hostname
        FROM devices d
        WHERE (CAST(:device_id AS INTEGER) IS NULL OR d.id = CAST(:device_id AS INTEGER))
          AND EXISTS (
              SELECT 1 FROM flow_minutes fm
              WHERE fm.device_id = d.id
                AND fm.bucket BETWEEN CAST(:start AS timestamptz)
                                  AND CAST(:end AS timestamptz)
          )
    )
    SELECT g.bucket,
           i.id AS device_id,
           i.mac,
           i.hostname,
           COALESCE(fm.bytes, 0)      AS bytes,
           COALESCE(fm.packets, 0)    AS packets,
           COALESCE(fm.flow_count, 0) AS flow_count
    FROM bucket_grid g
    CROSS JOIN included i
    LEFT JOIN flow_minutes fm
           ON fm.device_id = i.id
          AND fm.bucket = g.bucket
    ORDER BY g.bucket, i.id
    """
)


def traffic_series(
    db: Session, start: datetime, end: datetime, device_id: int | None = None
) -> list[dict]:
    """Dense per-device, per-minute traffic across the window.

    The CROSS JOIN against a generated bucket grid is the point of this query.
    `flow_minutes` only holds rows for minutes a device actually transmitted, so
    a sparse device (a thermostat that wakes up three times an hour) would come
    back as three points. A chart would then draw a straight line between them,
    implying steady traffic across 20 idle minutes. Zero-filling says what
    actually happened.
    """
    rows = db.execute(
        _SERIES_SQL, {"start": start, "end": end, "device_id": device_id}
    ).mappings()
    return [dict(row) for row in rows]


_DEVICES_SQL = text(
    """
    SELECT d.id,
           d.mac,
           d.ip,
           d.hostname,
           d.first_seen,
           d.last_seen,
           (d.last_seen >= CAST(:active_since AS timestamptz)) AS is_active,
           COALESCE(SUM(fm.bytes), 0)      AS bytes,
           COALESCE(SUM(fm.packets), 0)    AS packets,
           COALESCE(SUM(fm.flow_count), 0) AS flow_count
    FROM devices d
    -- LEFT JOIN, and the window predicate lives in the JOIN rather than a WHERE
    -- clause: moving it to WHERE would turn this back into an inner join and
    -- silently drop every device that was quiet during the window. An inventory
    -- that hides idle devices is not an inventory.
    LEFT JOIN flow_minutes fm
           ON fm.device_id = d.id
          AND fm.bucket BETWEEN CAST(:start AS timestamptz)
                            AND CAST(:end AS timestamptz)
    GROUP BY d.id
    ORDER BY bytes DESC, d.hostname
    """
)


def device_list(db: Session, start: datetime, end: datetime) -> list[dict]:
    """Every known device, with its totals over the window (zero if it was idle)."""
    active_since = datetime.now(timezone.utc) - timedelta(minutes=ACTIVE_WITHIN_MINUTES)
    rows = db.execute(
        _DEVICES_SQL, {"start": start, "end": end, "active_since": active_since}
    ).mappings()
    return [dict(row) for row in rows]


_TOP_SQL = text(
    """
    SELECT d.id AS device_id,
           d.mac,
           d.hostname,
           SUM(fm.bytes)               AS bytes,
           SUM(fm.packets)             AS packets,
           SUM(fm.flow_count)          AS flow_count,
           -- Window function over the aggregate: this totals every group in the
           -- window BEFORE the LIMIT is applied, so `share` is a fraction of all
           -- traffic rather than of the handful of rows returned.
           SUM(SUM(fm.bytes)) OVER ()  AS window_total
    FROM flow_minutes fm
    JOIN devices d ON d.id = fm.device_id
    WHERE fm.bucket BETWEEN CAST(:start AS timestamptz)
                        AND CAST(:end AS timestamptz)
    GROUP BY d.id
    ORDER BY bytes DESC
    LIMIT :limit
    """
)


def top_talkers(
    db: Session, start: datetime, end: datetime, limit: int
) -> tuple[list[dict], int]:
    """The `limit` busiest devices, plus the window's true total for shares."""
    rows = [
        dict(row)
        for row in db.execute(
            _TOP_SQL, {"start": start, "end": end, "limit": limit}
        ).mappings()
    ]
    # No rows means no traffic at all in the window, so the total is zero rather
    # than unknown.
    window_total = int(rows[0]["window_total"]) if rows else 0
    for row in rows:
        row.pop("window_total", None)
        row["share"] = (row["bytes"] / window_total) if window_total else 0.0
    return rows, window_total
