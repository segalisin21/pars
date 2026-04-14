from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import TargetingProfile
from app.targeting_ai import capture_messages_for_workspace, recompute_features_for_profile
from app.telethon_client import TelethonTelegramClient
from app.worker_jobs import get_worker_session_factory


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Capture candidate messages + recompute AI targeting for a profile.")
    p.add_argument("--workspace-id", type=int, required=True)
    p.add_argument("--profile-id", type=int, required=True)
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--max-messages-per-source", type=int, default=300)
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    ws = int(args.workspace_id)
    pid = int(args.profile_id)
    days = max(1, int(args.days))
    min_date = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0)

    sf = get_worker_session_factory()
    db = sf()
    try:
        prof = db.scalar(select(TargetingProfile).where(TargetingProfile.workspace_id == ws, TargetingProfile.id == pid))
        if prof is None:
            raise SystemExit("profile_not_found")
        tg = TelethonTelegramClient.from_env()
        cap = capture_messages_for_workspace(
            db,
            tg,
            workspace_id=ws,
            min_date=min_date,
            max_messages_per_source=int(args.max_messages_per_source),
        )
        n = recompute_features_for_profile(db, workspace_id=ws, profile=prof)
        db.commit()
        print(f"ok workspace_id={ws} profile_id={pid} captured={cap} features_upserted={n}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

