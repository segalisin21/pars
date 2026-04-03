# Telegram audience collector & inviter (v1) — Test plan

## Hard gate

All changes must keep the following passing:

```bash
pytest tests/ -v --tb=short
```

## Test strategy

### What we test (v1)

- **Alembic** (`tests/test_migrations.py`): `upgrade head` creates `alembic_version` and app tables; second run is a no-op (startup path uses the same code).
- **API contracts**:
  - create/list sources
  - create/list targets
  - start collect run, get status
  - start invite run, get status
  - consistent error format
- **Persistence and dedup**:
  - upsert candidates by `tg_user_id`
  - fallback dedup by normalized `username` when `tg_user_id` absent
- **Eligibility selection**:
  - suppressed users are excluded
  - already-success users excluded for the same target
  - cooldown window excludes recent attempts
- **Telegram error mapping**:
  - FloodWait → `flood_wait` and backoff behavior
  - privacy restrictions → `privacy_restricted` and suppression TTL

### What we do NOT test (v1)

- Real Telegram API integration (no network in tests).
- True timing/sleep-based pacing (avoid flaky sleeps).

## Test setup

### Python environment

Install pinned dependencies before running pytest:

```bash
pip install -r requirements-dev.txt
```

(`requirements-dev.txt` includes production deps plus `pytest`.)

### Database

- Use **in-memory SQLite** for tests.
- Create schema at test start; ensure isolation per test.

### Telegram client mocking

Implement a **fake Telegram client** with deterministic behavior:

- `get_participants(source_identifier)` returns a fixed set of users.
- `invite_to_target(target_identifier, tg_user_id)` returns:
  - success
  - already member
  - raises FloodWait-like error (fake exception)

Use dependency injection so API handlers / workers use the fake client during tests.

## Recommended test cases (minimum)

### API

- `POST /sources` → 201 + returned object
- `GET /sources` → includes created
- `POST /targets` → 201
- `POST /collect-runs` with unknown source id → 404 `source_not_found`
- `POST /invite-runs` with unknown target id → 404 `target_not_found`

### Dedup

- Insert candidate with `tg_user_id=1`; repeat from another source → still single candidate, provenance updated.
- Insert candidate without `tg_user_id` but with `username=TestUser`; repeat with `username=testuser` → dedup.

### Eligibility & suppression

- Suppressed candidate never selected for invite.
- Candidate with recent attempt not selected.

## Diagnostics

When tests fail:
- print API response bodies in assertions
- keep fixtures small and explicit

