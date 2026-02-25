from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Decision(str, Enum):
    NOW = "Now"
    LATER = "Later"
    NEVER = "Never"


class NotificationEvent(BaseModel):
    user_id: str = Field(..., alias="userid")
    event_type: str = Field(..., alias="eventtype")
    message: str | None = None
    title: str | None = None
    source: str | None = None
    priority_hint: str | None = Field(default=None, alias="priorityhint")
    timestamp: datetime
    channel: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str | None = Field(default=None, alias="dedupekey")
    expires_at: datetime | None = None

    model_config = {"populate_by_name": True}


class DecisionResponse(BaseModel):
    decision: Decision
    reason: str
    scheduled_for: datetime | None = None
    policy_version: str
    risk_score: float


class RuleConfig(BaseModel):
    policy_version: str = "v1"
    cooldown_seconds: int = 180
    max_per_hour: int = 15
    promotional_cap_per_day: int = 3
    near_duplicate_window_seconds: int = 300
    digest_delay_seconds: int = 600
    urgent_event_types: list[str] = Field(
        default_factory=lambda: ["security_alert", "payment_failed", "message_direct"]
    )
    suppress_event_types: list[str] = Field(default_factory=lambda: ["passive_tip"])
    promotional_event_types: list[str] = Field(default_factory=lambda: ["promotion", "upsell"])


class AuditRecord(BaseModel):
    event: NotificationEvent
    decision: DecisionResponse
    created_at: datetime


class UserHistory(BaseModel):
    user_id: str
    last_hour_events: list[NotificationEvent]
    audit_records: list[AuditRecord]
