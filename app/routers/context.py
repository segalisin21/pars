"""Shared dependencies passed into per-domain APIRouter factories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class RouteContext:
    get_db: Callable[..., Any]
    get_tg: Callable[..., Any]
    get_workspace_id: Callable[..., Any]
    verify_admin_token: Callable[..., Any]
    source_row_out: Callable[[Any], Any]
    rq_timeout_seconds: Callable[[str, int], int]
