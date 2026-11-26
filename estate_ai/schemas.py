import re
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

VISIT_TIME_ZONE = ZoneInfo("Asia/Kolkata")


def visit_tomorrow() -> date:
    return datetime.now(VISIT_TIME_ZONE).date() + timedelta(days=1)


def validate_visit_date(start_time: datetime) -> None:
    tomorrow = visit_tomorrow()
    if start_time.astimezone(VISIT_TIME_ZONE).date() != tomorrow:
        raise ValueError(
            f"Site visits can only be requested for tomorrow, {tomorrow:%d %b %Y} IST. Please choose a time that day."
        )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def normalize_phone(value: str) -> str:
    phone = re.sub(r"[\s()+-]", "", value)
    if not re.fullmatch(r"[1-9]\d{7,14}", phone):
        raise ValueError("Use an international phone number including country code")
    return phone


class ChatInput(StrictModel):
    phone: str
    text: str = Field(min_length=1, max_length=4000)
    event_id: str = Field(min_length=1, max_length=150, pattern=r"^[A-Za-z0-9_.:+=/-]+$")

    _phone = field_validator("phone")(normalize_phone)


class PropertyInterestInput(StrictModel):
    event_id: UUID
    property_id: str = Field(min_length=1, max_length=64)
    buyer_name: str = Field(min_length=1, max_length=80)
    phone: str = Field(max_length=40)
    whatsapp_consent: Literal[True]

    _phone = field_validator("phone")(normalize_phone)

    @field_validator("buyer_name", mode="before")
    @classmethod
    def clean_buyer_name(cls, value):
        return " ".join(value.split()) if isinstance(value, str) else value


class PropertyInput(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=80)
    locality: str = Field(default="", max_length=120)
    bedrooms: int = Field(ge=0, le=30)
    asking_price: int = Field(gt=0, le=2_000_000_000)
    available: bool = True
    description: str = Field(default="", max_length=6000)
    demo: bool = False
    details: dict[str, str] | None = None

    @field_validator("details")
    @classmethod
    def bounded_details(cls, value):
        if value is not None and (
            len(value) > 60 or any(len(k) > 80 or len(v) > 1000 for k, v in value.items())
        ):
            raise ValueError("Use at most 60 detail fields with short names and values")
        return value


class SearchArgs(StrictModel):
    city: str | None = Field(default=None, max_length=80)
    locality: str | None = Field(default=None, min_length=1, max_length=120)
    max_price: int | None = Field(default=None, gt=0)
    bedrooms: int | None = Field(default=None, ge=0, le=30)
    limit: int = Field(default=5, ge=1, le=10)
    exclude_seen: bool = False


class PropertyArgs(StrictModel):
    property_id: str = Field(min_length=1, max_length=64)


class RelatedArgs(StrictModel):
    property_id: str | None = Field(default=None, min_length=1, max_length=64)
    limit: int = Field(default=3, ge=1, le=5)
    exclude_seen: bool = True


class PreferenceArgs(StrictModel):
    location: str | None = Field(default=None, max_length=120)
    bedrooms: int | None = Field(default=None, ge=0, le=30)
    purpose: str | None = Field(default=None, max_length=160)
    timeline: str | None = Field(default=None, max_length=160)


class PriceArgs(StrictModel):
    kind: Literal["budget", "offer"]
    amount_inr: int = Field(gt=0, le=2_000_000_000)
    property_id: str | None = Field(default=None, max_length=64)


class VisitArgs(StrictModel):
    property_id: str = Field(min_length=1, max_length=64)
    start_time: datetime = Field(description="Requested time tomorrow in Asia/Kolkata, with a UTC offset.")

    @field_validator("start_time")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError(
                "Time must include an explicit UTC offset; default business zone is Asia/Kolkata"
            )
        return value


class HandoffArgs(StrictModel):
    reason: str = Field(min_length=1, max_length=300)
