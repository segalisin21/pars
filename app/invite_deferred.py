"""Invite outcomes that often need manual follow-up (link in DM, mutual contact, etc.)."""

from __future__ import annotations

# Failed attempts with these error_code values are included in CSV export for operators.
DEFERRED_INVITE_EXPORT_CODES: frozenset[str] = frozenset(
    {
        "privacy_restricted",
        "not_mutual_contact",
        "channel_private",
        "admin_required",
    }
)
