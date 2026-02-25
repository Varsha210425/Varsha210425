from datetime import datetime, timedelta, timezone

import pytest

from app.engine import PrioritizationEngine
from app.models import Decision, NotificationEvent, RuleConfig
from app.store import InMemoryStore


def mk_event(**kwargs):
    base = {
        "userid": "u1",
        "eventtype": "message_direct",
        "message": "You got a new message",
        "title": "New message",
        "source": "chat",
        "timestamp": datetime.now(timezone.utc),
        "channel": "push",
    }
    base.update(kwargs)
    return NotificationEvent(**base)


def test_exact_duplicate_suppressed() -> None:
    store = InMemoryStore()
    engine = PrioritizationEngine(store)
    ev = mk_event(dedupekey="abc")
    first = engine.decide(ev)
    second = engine.decide(ev)
    assert first.decision == Decision.NOW
    assert second.decision == Decision.NEVER
    assert "exact_duplicate" in second.reason


def test_near_duplicate_deferred() -> None:
    store = InMemoryStore()
    store.set_rules(RuleConfig(near_duplicate_window_seconds=1000))
    engine = PrioritizationEngine(store)
    e1 = mk_event(message="Package arriving at 2 PM", eventtype="update")
    e2 = mk_event(message="Package arriving at 2pm", eventtype="update", dedupekey="other")
    engine.decide(e1)
    d2 = engine.decide(e2)
    assert d2.decision == Decision.LATER


def test_non_urgent_rate_limited_to_later() -> None:
    store = InMemoryStore()
    store.set_rules(RuleConfig(max_per_hour=1, urgent_event_types=[]))
    engine = PrioritizationEngine(store)
    e1 = mk_event(eventtype="reminder", priorityhint="low")
    e2 = mk_event(eventtype="reminder", priorityhint="low", dedupekey="x2")
    assert engine.decide(e1).decision == Decision.NOW
    assert engine.decide(e2).decision == Decision.LATER


def test_expired_event_is_never() -> None:
    store = InMemoryStore()
    engine = PrioritizationEngine(store)
    e = mk_event(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert engine.decide(e).decision == Decision.NEVER


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(ValueError, match="timezone offset"):
        mk_event(timestamp=datetime(2026, 1, 1, 0, 0, 0))


def test_backdated_events_do_not_bypass_hourly_limit() -> None:
    store = InMemoryStore()
    store.set_rules(RuleConfig(max_per_hour=1, urgent_event_types=[]))
    engine = PrioritizationEngine(store)
    very_old = datetime.now(timezone.utc) - timedelta(days=365)
    first = mk_event(eventtype="reminder", priorityhint="low", timestamp=very_old)
    second = mk_event(eventtype="reminder", priorityhint="low", timestamp=very_old, dedupekey="x-2")

    assert engine.decide(first).decision == Decision.NOW
    # Should still be rate limited because we window using trusted ingestion time.
    assert engine.decide(second).decision == Decision.LATER
