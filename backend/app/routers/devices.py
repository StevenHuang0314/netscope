from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import queries
from app.db import get_db
from app.schemas import DeviceOut

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("", response_model=list[DeviceOut])
def list_devices(
    db: Session = Depends(get_db),
    minutes: int = Query(
        60,
        ge=1,
        le=1440,
        description="Window for the per-device totals, in minutes (max 24h).",
    ),
):
    """Every device ever seen, with its traffic over the last `minutes`.

    Devices idle during the window are still listed, with zero totals — the
    device inventory is about what exists on the network, not what is loud
    right now.
    """
    start, end = queries.window_bounds(minutes)
    return queries.device_list(db, start, end)
