from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class QueueConfig:
    redis_url: str | None
    queue_name: str


def get_queue_config() -> QueueConfig:
    redis_url = os.getenv("REDIS_URL") or None
    queue_name = os.getenv("RQ_QUEUE_NAME") or "default"
    return QueueConfig(redis_url=redis_url, queue_name=queue_name)


def is_queue_enabled() -> bool:
    return bool(get_queue_config().redis_url)


def get_rq_queue():
    from redis import Redis  # local import to keep optionality in local dev/tests
    from rq import Queue

    cfg = get_queue_config()
    if not cfg.redis_url:
        raise RuntimeError("REDIS_URL is not set")
    redis = Redis.from_url(cfg.redis_url)
    return Queue(name=cfg.queue_name, connection=redis)

