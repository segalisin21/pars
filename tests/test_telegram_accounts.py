from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import CollectRun, utcnow


def test_telegram_accounts_crud_requires_admin(monkeypatch, session_factory, fake_tg):
    monkeypatch.setenv("ADMIN_TOKEN", "z" * 32)
    app = create_app(session_factory=session_factory, tg_client=fake_tg)
    client = TestClient(app)
    r = client.post("/telegram-accounts", json={"label": "a", "session_string": "x" * 20})
    assert r.status_code == 401


def test_telegram_accounts_create_list_delete(monkeypatch, session_factory, fake_tg):
    tok = "y" * 32
    monkeypatch.setenv("ADMIN_TOKEN", tok)
    app = create_app(session_factory=session_factory, tg_client=fake_tg)
    client = TestClient(app)
    h = {"Authorization": f"Bearer {tok}"}
    r = client.post("/telegram-accounts", json={"label": "acc1", "session_string": "session_data_" * 5}, headers=h)
    assert r.status_code == 201
    body = r.json()
    assert body["label"] == "acc1"
    assert body["enabled"] is True
    aid = body["id"]

    lst = client.get("/telegram-accounts", headers=h).json()
    assert len(lst["items"]) == 1
    assert lst["items"][0]["id"] == aid

    d = client.delete(f"/telegram-accounts/{aid}", headers=h)
    assert d.status_code == 204

    lst2 = client.get("/telegram-accounts", headers=h).json()
    assert lst2["items"] == []


def test_collect_run_accepts_telegram_account_id(monkeypatch, session_factory, fake_tg):
    tok = "w" * 32
    monkeypatch.setenv("ADMIN_TOKEN", tok)
    app = create_app(session_factory=session_factory, tg_client=fake_tg)
    client = TestClient(app)
    h = {"Authorization": f"Bearer {tok}"}
    acc = client.post("/telegram-accounts", json={"label": "c", "session_string": "s" * 30}, headers=h).json()
    src = client.post("/sources", json={"type": "group", "identifier": "@src_acc", "enabled": True}, headers=h).json()
    r = client.post(
        "/collect-runs",
        json={"source_ids": [src["id"]], "telegram_account_id": acc["id"]},
        headers=h,
    )
    assert r.status_code == 202
    assert r.json()["telegram_account_id"] == acc["id"]


def test_telegram_app_credentials_get_put(monkeypatch, session_factory, fake_tg):
    tok = "a" * 32
    monkeypatch.setenv("ADMIN_TOKEN", tok)
    app = create_app(session_factory=session_factory, tg_client=fake_tg)
    client = TestClient(app)
    h = {"Authorization": f"Bearer {tok}"}

    g0 = client.get("/telegram/app-credentials", headers=h)
    assert g0.status_code == 200
    assert g0.json()["configured"] in {False, True}

    put = client.put("/telegram/app-credentials", json={"api_id": 123, "api_hash": "b" * 32}, headers=h)
    assert put.status_code == 200
    assert put.json()["configured"] is True
    assert put.json()["api_id"] == 123

    g1 = client.get("/telegram/app-credentials", headers=h)
    assert g1.status_code == 200
    assert g1.json()["configured"] is True
    assert g1.json()["api_id"] == 123


def test_telegram_accounts_status_busy(monkeypatch, session_factory, fake_tg):
    tok = "b" * 32
    monkeypatch.setenv("ADMIN_TOKEN", tok)
    app = create_app(session_factory=session_factory, tg_client=fake_tg)
    client = TestClient(app)
    h = {"Authorization": f"Bearer {tok}"}

    acc = client.post("/telegram-accounts", json={"label": "acc", "session_string": "s" * 30}, headers=h).json()

    db = session_factory()
    try:
        db.add(
            CollectRun(
                workspace_id=1,
                status="running",
                source_ids=[],
                telegram_account_id=acc["id"],
                stats={},
                started_at=utcnow(),
            )
        )
        db.commit()
    finally:
        db.close()

    st = client.get("/telegram-accounts/status", headers=h)
    assert st.status_code == 200
    body = st.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["account"]["id"] == acc["id"]
    assert body["items"][0]["busy"]["kind"] == "collect"


def test_telegram_accounts_spambot_check_enqueues(monkeypatch, session_factory, fake_tg):
    tok = "c" * 32
    monkeypatch.setenv("ADMIN_TOKEN", tok)
    app = create_app(session_factory=session_factory, tg_client=fake_tg)
    client = TestClient(app)
    h = {"Authorization": f"Bearer {tok}"}

    acc = client.post("/telegram-accounts", json={"label": "acc", "session_string": "s" * 30}, headers=h).json()

    class _Job:
        def __init__(self):
            self.id = "job123"

    class _Queue:
        def enqueue(self, *args, **kwargs):
            return _Job()

    import app.routers.telegram_accounts as ta

    monkeypatch.setattr(ta, "is_queue_enabled", lambda: True)
    monkeypatch.setattr(ta, "get_rq_queue", lambda: _Queue())

    r = client.post(f"/telegram-accounts/{acc['id']}/spambot/check", headers=h)
    assert r.status_code == 200
    assert r.json()["enqueued"] is True
    assert r.json()["job_id"] == "job123"


def test_telegram_accounts_inbox_returns_items(monkeypatch, session_factory, fake_tg):
    tok = "d" * 32
    monkeypatch.setenv("ADMIN_TOKEN", tok)
    app = create_app(session_factory=session_factory, tg_client=fake_tg)
    client = TestClient(app)
    h = {"Authorization": f"Bearer {tok}"}

    acc = client.post("/telegram-accounts", json={"label": "acc", "session_string": "s" * 30}, headers=h).json()

    async def _fake_fetch(db, *, account_id: int, peer: str, limit: int = 20):
        _ = db
        _ = limit
        assert account_id == acc["id"]
        assert peer == "777000"
        return {"ok": True, "error": None, "items": [{"id": 1, "date": None, "text": "code 12345", "out": False}]}

    import app.routers.telegram_accounts as ta

    monkeypatch.setattr(ta, "fetch_telegram_account_inbox_async", _fake_fetch)

    r = client.get(f"/telegram-accounts/{acc['id']}/inbox?peer=777000&limit=5", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["peer"] == "777000"
    assert body["items"][0]["text"] == "code 12345"
