from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import queries
from app.db import get_db
from app.models import Device
from app.schemas import SeriesOut, TopTalkersOut

router = APIRouter(prefix="/api/traffic", tags=["traffic"])


@router.get("/series", response_model=SeriesOut)
def traffic_series(
    db: Session = Depends(get_db),
    minutes: int = Query(
        60, ge=1, le=1440, description="How far back to read, in minutes (max 24h)."
    ),
    device_id: int | None = Query(
        None, description="Restrict to one device. Omit for every active device."
    ),
):
    """Per-device traffic per minute, gap-filled across the whole window.

    Every bucket in the window is present for every device that had traffic in
    it, zeros included, so a chart can plot the rows as-is without inventing
    values for the quiet minutes.
    """
    if device_id is not None:
        exists = db.execute(
            select(Device.id).where(Device.id == device_id)
        ).scalar_one_or_none()
        if exists is None:
            # Distinguish "no such device" from "device with no traffic" — both
            # would otherwise return an empty list and look identical.
            raise HTTPException(status_code=404, detail=f"no device {device_id}")

    start, end = queries.window_bounds(minutes)
    return SeriesOut(
        start=start,
        end=end,
        bucket_seconds=queries.BUCKET_SECONDS,
        points=queries.traffic_series(db, start, end, device_id),
    )


@router.get("/top", response_model=TopTalkersOut)
def top_talkers(
    db: Session = Depends(get_db),
    minutes: int = Query(60, ge=1, le=1440, description="Window in minutes (max 24h)."),
    limit: int = Query(5, ge=1, le=50, description="How many devices to return."),
):
    """The busiest devices by bytes over the window.

    `share` is each device's fraction of *all* traffic in the window, not just
    of the rows returned, so the listed shares legitimately sum to less than 1.
    """
    start, end = queries.window_bounds(minutes)
    talkers, window_total = queries.top_talkers(db, start, end, limit)
    return TopTalkersOut(
        start=start,
        end=end,
        window_total_bytes=window_total,
        talkers=talkers,
    )
