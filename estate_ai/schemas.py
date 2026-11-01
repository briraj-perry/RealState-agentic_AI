import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class SearchArgs(StrictModel):
    city: str | None = Field(default=None, max_length=80)
    locality: str | None = Field(default=None, min_length=1, max_length=120)
    max_price: int | None = Field(default=None, gt=0)
    bedrooms: int | None = Field(default=None, ge=0, le=30)
    limit: int = Field(default=3, ge=1, le=10)
    exclude_seen: bool = False


class PropertyArgs(StrictModel):
    property_id: str = Field(min_length=1, max_length=64)


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
    start_time: datetime

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
