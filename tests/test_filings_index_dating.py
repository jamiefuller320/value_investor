from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from value_investor.filings_index_dating import backfill, bodies_at, scan_fetched_at
from value_investor.ingest_discovery_scan import merge_discovery_into_index
from value_investor.library_decision_input_inventory import _index_as_of

KEY_SUMMARY = {
    "total": 2,
    "with_body": 1,
    "period_coverage": {"annual": {"total": 1, "with_body": 1}},
}
NO_KEY_SUMMARY = {
    "total": 1,
    "with_body": 0,
    "period_coverage": {"annual": {"total": 1, "with_body": 0}},
}


def _row(row_id: str, *, body: bool, period: str = "annual") -> dict:
    return {
        "id": row_id,
        "source": "rns",
        "headline": f"{period} report",
        "published_at": "2026-03-01T00:00:00+00:00",
        "url": f"https://example.com/{row_id}",
        "period": period,
        "category": "results",
        "summary": "",
        "has_body": body,
        "body_path": f"bodies/{row_id}.txt" if body else None,
        "priority": 1,
    }


def _index(fetched_at: str, rows: list[dict], **extra) -> dict:
    from value_investor.research.filings import summarize_filings

    return {
        "ticker": "AAA.L",
        "fetched_at": fetched_at,
        "summary": summarize_filings(rows),
        "filings": rows,
        **extra,
    }


def test_bodies_at_ignores_listing_stamps_and_takes_latest_body_pass():
    payload = {
        "fetched_at": "2026-10-01T00:00:00+00:00",
        "ch_refetched_at": "2026-10-05T00:00:00+00:00",
        "discovery_scan_at": "2026-11-10T00:00:00+00:00",
        "listing_refresh_at": "2026-11-10T00:00:00+00:00",
    }
    assert bodies_at(payload) == datetime(2026, 10, 5, tzinfo=UTC)


def test_scan_keeps_prior_stamp_unless_key_bodies_turn_on():
    now = datetime(2026, 11, 10, tzinfo=UTC)
    prior = {"fetched_at": "2026-10-01T00:00:00+00:00", "summary": KEY_SUMMARY}
    assert scan_fetched_at(prior, {"summary": KEY_SUMMARY}, now) == prior["fetched_at"]
    assert scan_fetched_at(prior, {"summary": NO_KEY_SUMMARY}, now) == prior["fetched_at"]
    off = {"fetched_at": "2026-10-01T00:00:00+00:00", "summary": NO_KEY_SUMMARY}
    assert scan_fetched_at(off, {"summary": KEY_SUMMARY}, now) == now.isoformat()
    assert scan_fetched_at(None, {"summary": KEY_SUMMARY}, now) == now.isoformat()


def test_listing_merge_does_not_move_fetched_at(tmp_path: Path):
    filings_dir = tmp_path / "AAA.L" / "sources" / "filings"
    filings_dir.mkdir(parents=True)
    stamp = "2026-10-01T00:00:00+00:00"
    (filings_dir / "filings_index.json").write_text(
        json.dumps(_index(stamp, [_row("old1", body=True)])), encoding="utf-8"
    )
    merge_discovery_into_index(
        filings_dir=filings_dir,
        ticker="AAA.L",
        company_name="AAA",
        discovered=[_row("new1", body=False, period="other")],
    )
    payload = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert payload["fetched_at"] == stamp
    assert payload["discovery_scan_at"] > stamp
    as_of = datetime(2026, 11, 9, 23, 59, tzinfo=UTC)
    assert _index_as_of("AAA.L", research_root=tmp_path, as_of=as_of)["key_bodies"] is True


def test_index_as_of_counts_body_refetch_after_session(tmp_path: Path):
    filings_dir = tmp_path / "AAA.L" / "sources" / "filings"
    filings_dir.mkdir(parents=True)
    payload = _index(
        "2026-10-01T00:00:00+00:00",
        [_row("old1", body=True)],
        ch_refetched_at="2026-11-10T08:00:00+00:00",
    )
    (filings_dir / "filings_index.json").write_text(json.dumps(payload), encoding="utf-8")
    before = datetime(2026, 11, 9, 23, 59, tzinfo=UTC)
    after = datetime(2026, 11, 10, 23, 59, tzinfo=UTC)
    assert _index_as_of("AAA.L", research_root=tmp_path, as_of=before)["key_bodies"] is False
    assert _index_as_of("AAA.L", research_root=tmp_path, as_of=after)["key_bodies"] is True


def _git(repo: Path, *args: str, when: str | None = None) -> None:
    env = None
    if when:
        import os

        env = {**os.environ, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when}
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def test_backfill_restores_first_key_bodies_commit(tmp_path: Path):
    repo = tmp_path
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    rel = Path("docs/data/research/AAA.L/sources/filings/filings_index.json")
    path = repo / rel
    path.parent.mkdir(parents=True)

    def commit(payload: dict, when: str) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "x", when=when)

    commit(
        _index("2026-09-01T00:00:00+00:00", [_row("a", body=False)]), "2026-09-01T12:00:00+00:00"
    )
    commit(_index("2026-09-20T00:00:00+00:00", [_row("a", body=True)]), "2026-09-20T12:00:00+00:00")
    commit(
        _index(
            "2026-11-10T00:00:00+00:00",
            [_row("a", body=True), _row("b", body=False, period="other")],
        ),
        "2026-11-10T12:00:00+00:00",
    )

    rows = backfill(repo, apply=True)
    assert [row.restored for row in rows] == ["2026-09-20T12:00:00+00:00"]
    text = path.read_text(encoding="utf-8")
    assert '"fetched_at": "2026-09-20T12:00:00+00:00"' in text
    assert text.count("\n") > 10
    assert backfill(repo, apply=False) == []


def test_backfill_skips_index_without_key_bodies(tmp_path: Path):
    repo = tmp_path
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    path = repo / "docs/data/research/AAA.L/sources/filings/filings_index.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_index("2026-11-10T00:00:00+00:00", [_row("a", body=False)])))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "x", when="2026-09-01T12:00:00+00:00")
    assert backfill(repo, apply=True) == []
