"""Runtime configuration, read once from the environment."""

import os


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


# Whether the API process should run the background ingest loop at all.
# Turn this off if you ever run more than one API worker/replica, otherwise
# every worker polls independently and you get duplicate flow rows.
INGEST_ENABLED: bool = _flag("INGEST_ENABLED", True)

# Seconds between polls. The synthetic source stamps flows with "now", so this
# also controls how many samples land in each 1-minute rollup bucket.
INGEST_INTERVAL_SECONDS: int = _int("INGEST_INTERVAL_SECONDS", 15)

# Which DataSource implementation to run. Only "synthetic" exists today; a real
# router/pcap source plugs in here without touching the scheduler.
INGEST_SOURCE: str = os.environ.get("INGEST_SOURCE", "synthetic").strip().lower()

# The simulated household's wall clock. Containers run in UTC, but "people are
# asleep at 3am" is a statement about local time — without this the synthetic
# traffic curve is shifted by your UTC offset.
LOCAL_TIMEZONE: str = os.environ.get("NETSCOPE_TIMEZONE", "America/Chicago").strip()

# Uvicorn configures its own loggers but leaves the root logger bare, so app
# log records go nowhere unless we attach a handler ourselves.
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").strip().upper()

# Browser origins allowed to call this API. The Vite dev server runs on 5173 and
# is a different origin from the API on 8000, so without this every fetch from
# the React app fails CORS preflight.
CORS_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]
