from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class FlowRecord:
    """A single network flow, independent of where it came from."""

    src_ip: str
    dst_ip: str
    src_port: int | None
    dst_port: int | None
    protocol: str
    bytes: int
    packets: int
    ts: datetime
    src_mac: str | None = None


class DataSource(ABC):
    """Anything that can produce network flows."""

    @abstractmethod
    def poll(self) -> list[FlowRecord]:
        """Return flows observed since the last call."""
        ...
