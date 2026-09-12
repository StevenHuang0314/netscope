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
    # Identity of the device that emitted the flow, when the source knows it.
    # A router API or DHCP lease table supplies these; a bare pcap may not.
    src_mac: str | None = None
    src_hostname: str | None = None


class DataSource(ABC):
    """Anything that can produce network flows."""

    @abstractmethod
    def poll(self) -> list[FlowRecord]:
        """Return flows observed since the last call."""
        ...
