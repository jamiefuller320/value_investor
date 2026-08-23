"""Feature flags for optional paper-learning review workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

DEFAULT_REVIEW_POLICY_PATH = Path("docs/data/paper_automation/review_policy.json")


def default_review_policy() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "paper_learning_review": {
            "enabled": True,
            "cadence": "weekly",
            "note": (
                "Observe-only agent synthesis over churn_health.json. "
                "Disable before live capital cutover."
            ),
        },
        "learning_director": {
            "enabled": True,
            "cadence": "weekly",
            "note": (
                "Observe-only Learning Director synthesis over analysis, exclusion, "
                "and vision roadmap. Disable before live capital cutover."
            ),
        },
    }


def load_review_policy(path: Path = DEFAULT_REVIEW_POLICY_PATH) -> dict[str, Any]:
    path = Path(path)
    raw = read_json(path) if path.exists() else None
    if not isinstance(raw, dict):
        return default_review_policy()
    policy = default_review_policy()
    incoming = raw.get("paper_learning_review")
    if isinstance(incoming, dict):
        policy["paper_learning_review"].update(incoming)
    director = raw.get("learning_director")
    if isinstance(director, dict):
        policy["learning_director"].update(director)
    return policy


def paper_learning_review_enabled(path: Path = DEFAULT_REVIEW_POLICY_PATH) -> bool:
    return bool(load_review_policy(path).get("paper_learning_review", {}).get("enabled", True))


def learning_director_enabled(path: Path = DEFAULT_REVIEW_POLICY_PATH) -> bool:
    return bool(load_review_policy(path).get("learning_director", {}).get("enabled", True))


def save_review_policy(policy: dict[str, Any], path: Path = DEFAULT_REVIEW_POLICY_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, policy, compact=False)
    return path
