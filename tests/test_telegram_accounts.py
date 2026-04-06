from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


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
