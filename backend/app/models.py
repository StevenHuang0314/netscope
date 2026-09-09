from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    mac: Mapped[str] = mapped_column(String(17), unique=True, index=True)
    ip: Mapped[str | None] = mapped_column(String(45))
    hostname: Mapped[str | None] = mapped_column(String(255))
    vendor: Mapped[str | None] = mapped_column(String(255))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    flows: Mapped[list["Flow"]] = relationship(back_populates="device")


class Flow(Base):
    __tablename__ = "flows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), index=True)
    src_ip: Mapped[str] = mapped_column(String(45))
    dst_ip: Mapped[str] = mapped_column(String(45))
    src_port: Mapped[int | None] = mapped_column(Integer)
    dst_port: Mapped[int | None] = mapped_column(Integer)
    protocol: Mapped[str] = mapped_column(String(8))
    bytes: Mapped[int] = mapped_column(BigInteger)
    packets: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    device: Mapped["Device"] = relationship(back_populates="flows")

    __table_args__ = (
        Index("ix_flows_device_ts", "device_id", "ts"),
    )
