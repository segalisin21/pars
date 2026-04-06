from __future__ import annotations

from app.models import CollectRun, Source
from app.services import process_collect_run


class ChatAdminRequiredError(Exception):
    pass


def test_collect_participants_admin_required_marks_failed(session_factory, fake_tg):
    db = session_factory()
    try:
        src = Source(workspace_id=1, type="group", identifier="@need_admin", enabled=True, collect_mode="participants")
        db.add(src)
        db.commit()
        db.refresh(src)

        run = CollectRun(workspace_id=1, status="queued", source_ids=[src.id], stats={})
        db.add(run)
        db.commit()
        db.refresh(run)

        def _raise(_ident: str):
            raise ChatAdminRequiredError("Chat admin privileges are required to do that in the specified chat")

        fake_tg.iter_participants = _raise  # type: ignore[assignment]

        process_collect_run(db, fake_tg, run)
        db.commit()

        db.refresh(run)
        assert run.status == "failed"
        assert run.stats["error"]["code"] == "tg_admin_required"
        assert "by_source_id" in run.stats
    finally:
        db.close()


def test_collect_auto_admin_required_falls_back_to_messages(session_factory, fake_tg):
    db = session_factory()
    try:
        src = Source(workspace_id=1, type="group", identifier="@need_admin2", enabled=True, collect_mode="auto")
        db.add(src)
        db.commit()
        db.refresh(src)

        run = CollectRun(workspace_id=1, status="queued", source_ids=[src.id], stats={})
        db.add(run)
        db.commit()
        db.refresh(run)

        def _raise(_ident: str):
            raise ChatAdminRequiredError("Chat admin privileges are required to do that in the specified chat")

        fake_tg.iter_participants = _raise  # type: ignore[assignment]
        fake_tg.message_senders_by_source["@need_admin2"] = []  # messages path runs but yields none

        process_collect_run(db, fake_tg, run)
        db.commit()

        db.refresh(run)
        assert run.status == "succeeded"
        by = run.stats["by_source_id"][str(src.id)]
        assert any(e.get("code") == "tg_admin_required" for e in by.get("errors", []))
        assert run.stats["discovered_from_participants"] == 0
    finally:
        db.close()

