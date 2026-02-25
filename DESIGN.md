# Notification Prioritization Engine Design

## High-level architecture

1. **Ingress API** (`POST /v1/notifications/decide`) receives notification events.
2. **Decision Engine** applies deterministic policy:
   - expiry checks
   - exact dedupe
   - near dedupe
   - fatigue controls
   - urgency override and conflict resolution
3. **State Store** (in-memory demo, replaceable with Redis + Postgres):
   - recent events
   - dedupe fingerprints
   - audit log
   - dynamic rules
4. **Rule Config API** (`GET/POST /v1/rules`) allows policy changes without code deploy.
5. **Audit/History API** (`GET /v1/users/{user_id}/history`) gives explainability.
6. **Optional AI Advisor** (best effort): enriches reason text only; decision path is rule-first and fail-safe.

## Decision strategy (Now / Later / Never)

- **Never**
  - event expired
  - event type in suppress list
  - exact duplicate inside dedupe window
  - promotional daily cap reached
- **Later**
  - near-duplicate to be batched into digest
  - hourly cap reached for non-urgent events
  - same-channel cooldown active for non-urgent events
- **Now**
  - event passes dedupe/fatigue checks
  - urgent events can bypass fatigue limits, but are still auditable

## Duplicate prevention

- **Exact duplicates**: use `dedupekey` when present; fallback to stable hash over user+event/channel/text/source.
- **Near duplicates**:
  - token fingerprint match
  - or Jaccard similarity >= 0.82 over normalized title/message for same event type and user

## Alert fatigue handling

- Per-user **max notifications per hour**
- Per-channel **cooldown**
- Per-day **promotional cap**
- **Digest defer** for near duplicates

## Fallback and reliability

- AI hint path executes with strict timeout (`20ms` default).
- On timeout/error, engine uses deterministic rules and logs fallback marker in reason.
- Important notifications are not silently dropped because every decision is audited.

## Minimal data model

- `NotificationEvent`
- `RuleConfig`
- `DecisionResponse`
- `AuditRecord`
- rolling user history + fingerprints

## Monitoring plan

Track:
- decision distribution (`now/later/never`)
- dedupe hit rates (exact vs near)
- fatigue suppress/defer rate
- urgent pass-through count
- AI fallback rate/timeouts
- decision latency p95/p99
