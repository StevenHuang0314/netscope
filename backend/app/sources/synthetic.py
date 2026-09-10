import random
from datetime import datetime, timezone

from app.sources.base import DataSource, FlowRecord

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


def _diurnal_multiplier(hour: int) -> float:
    """Traffic is low overnight, peaks in the evening."""
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

    def poll(self) -> list[FlowRecord]:
        now = datetime.now(timezone.utc)
        multiplier = _diurnal_multiplier(now.hour)
        flows: list[FlowRecord] = []

        for mac, ip, _hostname, profile in DEVICES:
            expected = PROFILE_RATE[profile] * multiplier
            count = max(0, int(random.gauss(expected, expected * 0.4)))

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
                    )
                )

        return flows
