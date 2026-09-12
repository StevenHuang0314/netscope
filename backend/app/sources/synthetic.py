import logging
import math
import random
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app import config
from app.sources.base import DataSource, FlowRecord

log = logging.getLogger(__name__)

# A plausible home network: mixed device types with different traffic profiles.
DEVICES = [
    # (mac, ip, hostname, profile)
    ("a4:83:e7:1c:2f:90", "192.168.1.10", "macbook-pro", "workstation"),
    ("f0:18:98:44:c1:3b", "192.168.1.11", "iphone", "mobile"),
    ("dc:a6:32:8e:71:04", "192.168.1.20", "raspberrypi", "server"),
    ("18:b4:30:9a:55:e2", "192.168.1.30", "nest-thermostat", "iot"),
    ("44:65:0d:22:b8:71", "192.168.1.31", "echo-dot", "iot"),
    ("00:17:88:60:0f:aa", "192.168.1.32", "hue-bridge", "iot"),
    ("b8:27:eb:d4:19:5c", "192.168.1.40", "smart-tv", "streaming"),
]

# Where traffic goes: (ip, port, protocol, weight, byte_range or None)
# byte_range None means "use the device profile's range".
DESTINATIONS = [
    ("142.250.190.78", 443, "TCP", 0.30, None),        # Google
    ("151.101.1.140", 443, "TCP", 0.15, None),         # Fastly CDN
    ("52.94.236.248", 443, "TCP", 0.15, None),         # AWS
    ("192.168.1.1", 53, "UDP", 0.20, (60, 512)),       # local DNS — always small
    ("104.244.42.129", 443, "TCP", 0.10, None),        # social
    ("23.246.2.14", 443, "TCP", 0.10, None),           # streaming CDN
]

# Bytes per flow by device profile: (min, max). Wildly different by device type.
PROFILE_BYTES = {
    "workstation": (2_000, 500_000),
    "mobile": (1_000, 200_000),
    "server": (500, 50_000),
    "iot": (200, 5_000),
    "streaming": (100_000, 8_000_000),
}

# Relative chattiness: how many flows a device tends to emit per poll.
PROFILE_RATE = {
    "workstation": 4.0,
    "mobile": 2.0,
    "server": 1.5,
    "iot": 0.4,
    "streaming": 3.0,
}


def _local_zone() -> ZoneInfo | timezone:
    """The household's wall clock — NOT the server's.

    The diurnal curve below describes when people are home and awake, which is a
    fact about local time. Containers run in UTC, so reading the UTC hour makes
    the simulation think a Chicago evening is the middle of the night.
    """
    try:
        return ZoneInfo(config.LOCAL_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning(
            "unknown NETSCOPE_TIMEZONE %r; falling back to UTC",
            config.LOCAL_TIMEZONE,
        )
        return timezone.utc


def _poisson(lam: float) -> int:
    """Draw a flow count for one device in one poll (Knuth's algorithm).

    Flow arrivals are a counting process, so Poisson is the right shape. The
    obvious-looking `int(random.gauss(mu, sigma))` is not: int() truncates
    toward zero, so any rate below 1.0 collapses to almost always zero — a
    device expected to emit 0.6 flows emits one about 5% of the time instead of
    ~55% — and even busy devices lose ~20% of their traffic to the floor.
    """
    if lam <= 0:
        return 0
    target = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        p *= random.random()
        if p <= target:
            return k
        k += 1


def _diurnal_multiplier(hour: int) -> float:
    """Traffic is low overnight, peaks in the evening. `hour` is LOCAL."""
    if 0 <= hour < 6:
        return 0.15
    if 6 <= hour < 9:
        return 0.6
    if 9 <= hour < 17:
        return 0.8
    if 17 <= hour < 23:
        return 1.4
    return 0.5


def _pick_destination() -> tuple[str, int, str, tuple[int, int] | None]:
    r = random.random()
    cumulative = 0.0
    for ip, port, proto, weight, byte_range in DESTINATIONS:
        cumulative += weight
        if r <= cumulative:
            return ip, port, proto, byte_range
    last = DESTINATIONS[-1]
    return last[0], last[1], last[2], last[4]


class SyntheticSource(DataSource):
    """Generates plausible home-network traffic. Used when no real capture is available."""

    def __init__(self) -> None:
        self._zone = _local_zone()

    def poll(self) -> list[FlowRecord]:
        # Flows are stamped in UTC; only the activity curve is read in local time.
        now = datetime.now(timezone.utc)
        multiplier = _diurnal_multiplier(now.astimezone(self._zone).hour)
        flows: list[FlowRecord] = []

        for mac, ip, hostname, profile in DEVICES:
            expected = PROFILE_RATE[profile] * multiplier
            count = _poisson(expected)

            for _ in range(count):
                dst_ip, dst_port, protocol, byte_range = _pick_destination()
                lo, hi = byte_range if byte_range else PROFILE_BYTES[profile]
                size = int(random.triangular(lo, hi, lo * 2))
                flows.append(
                    FlowRecord(
                        src_ip=ip,
                        dst_ip=dst_ip,
                        src_port=random.randint(32768, 60999),
                        dst_port=dst_port,
                        protocol=protocol,
                        bytes=size,
                        packets=max(1, size // 1400),
                        ts=now,
                        src_mac=mac,
                        src_hostname=hostname,
                    )
                )

        return flows
