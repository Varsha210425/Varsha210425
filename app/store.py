from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.models import AuditRecord, NotificationEvent, RuleConfig


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RecentFingerprint:
    fingerprint: str
    event: NotificationEvent
    seen_at: datetime


@dataclass
class StoredEvent:
    event: NotificationEvent
    received_at: datetime


class InMemoryStore:
    """State store suitable for demos/tests. Swap with Redis or DB in production."""

    def __init__(self) -> None:
        self._rules = RuleConfig()
        self._events_by_user: dict[str, deque[StoredEvent]] = defaultdict(deque)
        self._audit_by_user: dict[str, deque[AuditRecord]] = defaultdict(deque)
        self._fingerprints_by_user: dict[str, deque[RecentFingerprint]] = defaultdict(deque)
        self._exact_seen: dict[tuple[str, str], datetime] = {}

    def get_rules(self) -> RuleConfig:
        return self._rules

    def set_rules(self, rules: RuleConfig) -> RuleConfig:
        self._rules = rules
        return self._rules

    def add_event(self, event: NotificationEvent, received_at: datetime) -> None:
        q = self._events_by_user[event.user_id]
        q.append(StoredEvent(event=event, received_at=received_at))
        self._trim_events(event.user_id)

    def add_audit(self, user_id: str, record: AuditRecord) -> None:
        q = self._audit_by_user[user_id]
        q.append(record)
        self._trim_audit(user_id)

    def recent_events(self, user_id: str, within_seconds: int) -> list[NotificationEvent]:
        self._trim_events(user_id)
        cutoff = utc_now() - timedelta(seconds=within_seconds)
        return [stored.event for stored in self._events_by_user[user_id] if stored.received_at >= cutoff]

    def recent_audit(self, user_id: str, limit: int = 50) -> list[AuditRecord]:
        self._trim_audit(user_id)
        return list(self._audit_by_user[user_id])[-limit:]

    def mark_exact_seen(self, user_id: str, key: str, seen_at: datetime) -> None:
        self._exact_seen[(user_id, key)] = seen_at

    def exact_seen_within(self, user_id: str, key: str, within_seconds: int) -> bool:
        seen_at = self._exact_seen.get((user_id, key))
        if not seen_at:
            return False
        return seen_at >= utc_now() - timedelta(seconds=within_seconds)

    def push_fingerprint(self, user_id: str, fingerprint: str, event: NotificationEvent, seen_at: datetime) -> None:
        q = self._fingerprints_by_user[user_id]
        q.append(RecentFingerprint(fingerprint=fingerprint, event=event, seen_at=seen_at))
        self._trim_fingerprints(user_id)

    def recent_fingerprints(self, user_id: str, within_seconds: int) -> list[RecentFingerprint]:
        self._trim_fingerprints(user_id)
        cutoff = utc_now() - timedelta(seconds=within_seconds)
        return [fp for fp in self._fingerprints_by_user[user_id] if fp.seen_at >= cutoff]

    def _trim_events(self, user_id: str) -> None:
        cutoff = utc_now() - timedelta(days=2)
        q = self._events_by_user[user_id]
        while q and q[0].received_at < cutoff:
            q.popleft()

    def _trim_audit(self, user_id: str) -> None:
        cutoff = utc_now() - timedelta(days=7)
        q = self._audit_by_user[user_id]
        while q and q[0].created_at < cutoff:
            q.popleft()

    def _trim_fingerprints(self, user_id: str) -> None:
        cutoff = utc_now() - timedelta(hours=6)
        q = self._fingerprints_by_user[user_id]
        while q and q[0].seen_at < cutoff:
            q.popleft()
