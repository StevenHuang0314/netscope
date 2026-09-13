"""Response models for the read API.

Byte counts are returned as integers, not formatted strings — formatting is a
presentation concern and the frontend needs the raw number to chart it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DeviceOut(BaseModel):
    """A device plus its activity over the requested window."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    mac: str
    ip: str | None
    hostname: str | None
    first_seen: datetime
    last_seen: datetime
    # "Has this device been heard from recently", not "does it have a row".
    is_active: bool
    bytes: int
    packets: int
    flow_count: int


class SeriesPoint(BaseModel):
    """One device's traffic in one minute. Always present, even when zero."""

    bucket: datetime
    device_id: int
    mac: str
    hostname: str | None
    bytes: int
    packets: int
    flow_count: int


class SeriesOut(BaseModel):
    """A dense grid: every bucket in the window, for every device in it.

    `points` is flat rather than grouped by device or keyed by timestamp. A flat
    list serves a line chart, a stacked area chart, a table and a CSV export
    equally well; the client pivots it once into whatever shape it needs. Baking
    one chart's shape into the API would make the other three awkward.
    """

    start: datetime
    end: datetime
    bucket_seconds: int
    points: list[SeriesPoint]


class TopTalker(BaseModel):
    device_id: int
    mac: str
    hostname: str | None
    bytes: int
    packets: int
    flow_count: int
    # Fraction of ALL traffic in the window, including devices below the cut.
    share: float


class TopTalkersOut(BaseModel):
    start: datetime
    end: datetime
    window_total_bytes: int
    talkers: list[TopTalker]
