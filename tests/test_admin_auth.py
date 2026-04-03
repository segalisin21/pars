from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_post_sources_returns_401_when_admin_token_set_and_header_missing(monkeypatch, session_factory, fake_tg):
    monkeypatch.setenv("ADMIN_TOKEN", "z" * 32)
    app = create_app(session_factory=session_factory, tg_client=fake_tg)
    client = TestClient(app)
    r = client.post("/sources", json={"type": "group", "identifier": "@noauth", "enabled": True})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_post_sources_returns_401_when_bearer_wrong_length(monkeypatch, session_factory, fake_tg):
    monkeypatch.setenv("ADMIN_TOKEN", "z" * 32)
    app = create_app(session_factory=session_factory, tg_client=fake_tg)
    client = TestClient(app)
    r = client.post(
        "/sources",
        json={"type": "group", "identifier": "@bad", "enabled": True},
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401


def test_post_sources_succeeds_with_valid_bearer(monkeypatch, session_factory, fake_tg):
    tok = "z" * 32
    monkeypatch.setenv("ADMIN_TOKEN", tok)
    app = create_app(session_factory=session_factory, tg_client=fake_tg)
    client = TestClient(app)
    r = client.post(
        "/sources",
        json={"type": "group", "identifier": "@okauth", "enabled": True},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 201
    assert r.json()["identifier"] == "okauth"
