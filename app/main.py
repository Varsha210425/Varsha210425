from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from datetime import datetime

from fastapi import FastAPI

from app.engine import PrioritizationEngine
from app.models import DecisionResponse, NotificationEvent, RuleConfig, UserHistory
from app.store import InMemoryStore

app = FastAPI(title="Notification Prioritization Engine", version="0.1.0")
store = InMemoryStore()
engine = PrioritizationEngine(store)
executor = ThreadPoolExecutor(max_workers=4)


@dataclass
class AIAdvisor:
    enabled: bool = False
    timeout_ms: int = 20

    def suggest(self, event: NotificationEvent) -> str | None:
        if not self.enabled:
            return None
        # Placeholder for remote AI call.
        # Must be best-effort only; decision engine continues if this path is slow/failing.
        return f"ai_hint:{event.event_type}"


advisor = AIAdvisor(enabled=False)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/notifications/decide", response_model=DecisionResponse)
def decide_notification(event: NotificationEvent) -> DecisionResponse:
    ai_hint = _safe_ai_hint(event)
    decision = engine.decide(event)
    if ai_hint:
        decision.reason = f"{decision.reason};{ai_hint}"
    return decision


@app.get("/v1/rules", response_model=RuleConfig)
def get_rules() -> RuleConfig:
    return store.get_rules()


@app.post("/v1/rules", response_model=RuleConfig)
def update_rules(rules: RuleConfig) -> RuleConfig:
    return store.set_rules(rules)


@app.get("/v1/users/{user_id}/history", response_model=UserHistory)
def user_history(user_id: str) -> UserHistory:
    return UserHistory(
        user_id=user_id,
        last_hour_events=store.recent_events(user_id, within_seconds=3600),
        audit_records=store.recent_audit(user_id, limit=100),
    )


@app.get("/v1/metrics")
def metrics_snapshot() -> dict[str, int | str | datetime]:
    rules = store.get_rules()
    return {
        "policy_version": rules.policy_version,
        "users_tracked": len(store._events_by_user),
        "audit_users": len(store._audit_by_user),
    }


def _safe_ai_hint(event: NotificationEvent) -> str | None:
    fut = executor.submit(advisor.suggest, event)
    try:
        return fut.result(timeout=advisor.timeout_ms / 1000)
    except TimeoutError:
        return "ai_unavailable_timeout_fallback_to_rules"
    except Exception:
        return "ai_unavailable_error_fallback_to_rules"
