from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
import re

from app.models import AuditRecord, Decision, DecisionResponse, NotificationEvent
from app.store import InMemoryStore, utc_now


class PrioritizationEngine:
    def __init__(self, store: InMemoryStore) -> None:
        self.store = store

    def decide(self, event: NotificationEvent) -> DecisionResponse:
        rules = self.store.get_rules()
        now = utc_now()

        if event.expires_at and event.expires_at <= now:
            return self._record(
                event,
                DecisionResponse(
                    decision=Decision.NEVER,
                    reason="expired_before_delivery",
                    policy_version=rules.policy_version,
                    risk_score=0.0,
                ),
            )

        if event.event_type in rules.suppress_event_types:
            return self._record(
                event,
                DecisionResponse(
                    decision=Decision.NEVER,
                    reason="event_type_suppressed_by_policy",
                    policy_version=rules.policy_version,
                    risk_score=0.2,
                ),
            )

        exact_key = event.dedupe_key or self._stable_dedupe_key(event)
        if self.store.exact_seen_within(event.user_id, exact_key, rules.near_duplicate_window_seconds):
            return self._record(
                event,
                DecisionResponse(
                    decision=Decision.NEVER,
                    reason="exact_duplicate_within_window",
                    policy_version=rules.policy_version,
                    risk_score=0.1,
                ),
            )

        fingerprint = self._fingerprint(event)
        if self._is_near_duplicate(event, fingerprint, rules.near_duplicate_window_seconds):
            return self._record(
                event,
                DecisionResponse(
                    decision=Decision.LATER,
                    reason="near_duplicate_deferred_for_digest",
                    scheduled_for=now + timedelta(seconds=rules.digest_delay_seconds),
                    policy_version=rules.policy_version,
                    risk_score=0.35,
                ),
            )

        last_hour = self.store.recent_events(event.user_id, within_seconds=3600)
        recent_count = len(last_hour)
        is_urgent = self._is_urgent(event)
        is_promo = event.event_type in rules.promotional_event_types

        if is_promo and self._promo_count_today(event.user_id) >= rules.promotional_cap_per_day:
            return self._record(
                event,
                DecisionResponse(
                    decision=Decision.NEVER,
                    reason="promotional_daily_cap_reached",
                    policy_version=rules.policy_version,
                    risk_score=0.25,
                ),
            )

        if recent_count >= rules.max_per_hour and not is_urgent:
            return self._record(
                event,
                DecisionResponse(
                    decision=Decision.LATER,
                    reason="user_hourly_cap_reached_non_urgent",
                    scheduled_for=now + timedelta(seconds=rules.cooldown_seconds),
                    policy_version=rules.policy_version,
                    risk_score=0.45,
                ),
            )

        if self._in_cooldown(event, rules.cooldown_seconds) and not is_urgent:
            return self._record(
                event,
                DecisionResponse(
                    decision=Decision.LATER,
                    reason="channel_cooldown_active",
                    scheduled_for=now + timedelta(seconds=rules.cooldown_seconds),
                    policy_version=rules.policy_version,
                    risk_score=0.4,
                ),
            )

        risk = 0.75 if is_urgent else 0.55
        return self._record(
            event,
            DecisionResponse(
                decision=Decision.NOW,
                reason="passes_dedupe_and_fatigue_checks",
                policy_version=rules.policy_version,
                risk_score=risk,
            ),
        )

    def _record(self, event: NotificationEvent, response: DecisionResponse) -> DecisionResponse:
        now = utc_now()
        self.store.mark_exact_seen(event.user_id, event.dedupe_key or self._stable_dedupe_key(event), now)
        self.store.push_fingerprint(event.user_id, self._fingerprint(event), event, now)
        self.store.add_event(event, received_at=now)
        self.store.add_audit(event.user_id, AuditRecord(event=event, decision=response, created_at=now))
        return response

    def _stable_dedupe_key(self, event: NotificationEvent) -> str:
        base = "|".join(
            [
                event.user_id,
                event.event_type,
                event.channel,
                self._normalize_text(event.title or ""),
                self._normalize_text(event.message or ""),
                (event.source or ""),
            ]
        )
        return sha256(base.encode("utf-8")).hexdigest()[:20]

    def _fingerprint(self, event: NotificationEvent) -> str:
        text = f"{event.title or ''} {event.message or ''} {event.event_type}"
        tokens = sorted(set(self._normalize_text(text).split()))
        return sha256(" ".join(tokens).encode("utf-8")).hexdigest()[:16]

    def _is_near_duplicate(self, event: NotificationEvent, fingerprint: str, within_seconds: int) -> bool:
        for recent in self.store.recent_fingerprints(event.user_id, within_seconds=within_seconds):
            if recent.event.event_type != event.event_type:
                continue
            if recent.fingerprint == fingerprint:
                return True
            score = self._jaccard_similarity(
                self._normalize_text((recent.event.message or "") + " " + (recent.event.title or "")).split(),
                self._normalize_text((event.message or "") + " " + (event.title or "")).split(),
            )
            if score >= 0.82:
                return True
        return False

    def _promo_count_today(self, user_id: str) -> int:
        todays = self.store.recent_events(user_id, within_seconds=86400)
        promo_types = set(self.store.get_rules().promotional_event_types)
        return sum(1 for ev in todays if ev.event_type in promo_types)

    def _in_cooldown(self, event: NotificationEvent, cooldown_seconds: int) -> bool:
        recent = self.store.recent_events(event.user_id, within_seconds=cooldown_seconds)
        return any(ev.channel == event.channel for ev in recent)

    def _is_urgent(self, event: NotificationEvent) -> bool:
        rules = self.store.get_rules()
        priority = (event.priority_hint or "").lower()
        return event.event_type in rules.urgent_event_types or priority in {"urgent", "high", "critical"}

    @staticmethod
    def _normalize_text(value: str) -> str:
        value = value.lower().strip()
        value = re.sub(r"\s+", " ", value)
        value = re.sub(r"[^a-z0-9 ]", "", value)
        return value

    @staticmethod
    def _jaccard_similarity(tokens_a: list[str], tokens_b: list[str]) -> float:
        set_a = set(tokens_a)
        set_b = set(tokens_b)
        if not set_a and not set_b:
            return 1.0
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)
