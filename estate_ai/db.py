from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now() -> float:
    return datetime.now(UTC).timestamp()


def uid() -> str:
    return uuid4().hex


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"
    phone: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    last_inbound: Mapped[float] = mapped_column(Float, default=0)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=now, index=True)


class TestSession(Base):
    __tablename__ = "test_sessions"
    phone: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    created: Mapped[float] = mapped_column(Float, default=now)


class Property(Base):
    __tablename__ = "properties"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(80), index=True)
    locality: Mapped[str] = mapped_column(String(120), default="")
    bedrooms: Mapped[int] = mapped_column(Integer)
    asking_price: Mapped[int] = mapped_column(Integer)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    verified_at: Mapped[float] = mapped_column(Float, default=now)
    description: Mapped[str] = mapped_column(Text, default="")
    demo: Mapped[bool] = mapped_column(Boolean, default=False)


class PropertyPhoto(Base):
    __tablename__ = "property_photos"
    __table_args__ = (UniqueConstraint("property_id", "digest"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), index=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    digest: Mapped[str] = mapped_column(String(64))
    created: Mapped[float] = mapped_column(Float, default=now)


class PropertyMetadata(Base):
    __tablename__ = "property_metadata"
    property_id: Mapped[str] = mapped_column(ForeignKey("properties.id"), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class InventoryImport(Base):
    __tablename__ = "inventory_imports"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    filename: Mapped[str] = mapped_column(String(200))
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    created: Mapped[float] = mapped_column(Float, default=now)


class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[str] = mapped_column(Text)
    source_message_id: Mapped[str] = mapped_column(String(160), index=True)
    confirmation_message_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="pending_confirmation")
    created: Mapped[float] = mapped_column(Float, default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    text: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[float] = mapped_column(Float, default=now)
    error: Mapped[str] = mapped_column(String(80), default="")
    created: Mapped[float] = mapped_column(Float, default=now)


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    body: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    provider_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    error: Mapped[str] = mapped_column(String(80), default="")
    created: Mapped[float] = mapped_column(Float, default=now)


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[float] = mapped_column(Float, default=now)


def connect(url: str):
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
