"""Durable Accept / Comment / reply labels for the entry_blind queue.

Reuses the Package M labels schema from post-sale reviews, but a **separate**
store file so outcome-coupled post-sale cards cannot leak into blind intake.
``influences_live=false`` always.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from value_investor.post_sale_review_labels import (
    ACTION_KINDS,
    CLEARING_ACTION_KINDS,
    EVENT_KINDS,
    REPLY_STUB_TEXT,
    SCHEMA_VERSION,
    actioned_episode_keys,
    comments_awaiting_reply,
    empty_labels_store,
    heal_active_replies_file,
    is_actioned,
    load_post_sale_review_labels,
    prune_active_replies,
    record_accept,
    record_comment,
    record_duplicate,
    reply_review_id,
)

LABELS_FILENAME = "entry_blind_review_labels.json"


def load_entry_blind_review_labels(data_dir: Path) -> dict[str, Any]:
    return load_post_sale_review_labels(data_dir, filename=LABELS_FILENAME)


def heal_entry_blind_replies_file(data_dir: Path) -> dict[str, Any]:
    return heal_active_replies_file(data_dir, filename=LABELS_FILENAME)


def record_entry_blind_accept(
    data_dir: Path,
    **kwargs: Any,
) -> dict[str, Any]:
    return record_accept(data_dir, filename=LABELS_FILENAME, **kwargs)


def record_entry_blind_comment(
    data_dir: Path,
    **kwargs: Any,
) -> dict[str, Any]:
    return record_comment(data_dir, filename=LABELS_FILENAME, **kwargs)


def record_entry_blind_duplicate(
    data_dir: Path,
    **kwargs: Any,
) -> dict[str, Any]:
    return record_duplicate(data_dir, filename=LABELS_FILENAME, **kwargs)


__all__ = [
    "ACTION_KINDS",
    "CLEARING_ACTION_KINDS",
    "EVENT_KINDS",
    "LABELS_FILENAME",
    "REPLY_STUB_TEXT",
    "SCHEMA_VERSION",
    "actioned_episode_keys",
    "comments_awaiting_reply",
    "empty_labels_store",
    "heal_entry_blind_replies_file",
    "is_actioned",
    "load_entry_blind_review_labels",
    "prune_active_replies",
    "record_entry_blind_accept",
    "record_entry_blind_comment",
    "record_entry_blind_duplicate",
    "reply_review_id",
]
