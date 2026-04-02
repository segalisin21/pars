from __future__ import annotations

import os

from redis import Redis
from rq import Worker


def main() -> None:
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise SystemExit("REDIS_URL is required for worker")

    queue_name = os.getenv("RQ_QUEUE_NAME") or "default"
    conn = Redis.from_url(redis_url)
    # Avoid rq.Connection import differences across rq versions.
    w = Worker([queue_name], connection=conn)
    w.work(with_scheduler=False)


if __name__ == "__main__":
    main()

