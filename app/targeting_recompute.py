from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from app.targeting import TargetingParams, recompute_candidate_features
from app.telethon_client import TelethonTelegramClient
from app.worker_jobs import get_worker_session_factory


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Recompute candidate targeting features (worker / Telethon).")
    p.add_argument("--workspace-id", type=int, required=True)
    p.add_argument("--source-id", type=int, action="append", default=[])
    p.add_argument("--days", type=int, default=14, help="How many days back to scan messages (default 14).")
    p.add_argument("--max-messages-per-source", type=int, default=200)
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    ws = int(args.workspace_id)
    src_ids = [int(x) for x in (args.source_id or [])]
    days = max(1, int(args.days))
    min_date = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0)
    params = TargetingParams(min_message_date=min_date, max_messages_per_source=max(1, int(args.max_messages_per_source)))

    sf = get_worker_session_factory()
    db = sf()
    try:
        tg = TelethonTelegramClient.from_env()
        n = recompute_candidate_features(db, tg, workspace_id=ws, source_ids=src_ids or None, params=params)
        db.commit()
        print(f"ok workspace_id={ws} upserted={n}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

