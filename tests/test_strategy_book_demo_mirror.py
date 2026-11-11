"""Strategy-book demo mirror: planning, safety, ledger, and ops findings.

HTTP is mocked. No test opens a network connection.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from value_investor.strategy_book_demo_mirror import (
    CATCHUP_ATTEMPT_LIMIT,
    DEMO_KEY_ENV,
    DEMO_SECRET_ENV,
    ORDER_CAP,
    TITLE_MISMATCH,
    TITLE_NOT_CONFIGURED,
    TITLE_ORDERS_PLACED,
    TITLE_SLIPPAGE,
    TITLE_STUCK,
    DemoMirrorSafetyError,
    DemoOrderRejected,
    DemoRateLimited,
    DemoTransport,
    DemoTransportError,
    _RefuseRedirect,
    apply_order_cap,
    attach_exit_quantities,
    build_plans,
    compute_slippage,
    demo_base_url,
    demo_credentials,
    findings_from_ledger,
    ingest_statement,
    main,
    note_delistings,
    reconcile,
    run_mirror,
)
from value_investor.t212_client import DEMO_BASE, LIVE_BASE

NOW = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
AFTER_CLOSE = datetime(2026, 11, 11, 17, 0, tzinfo=UTC)
SIGNAL = "2026-11-10"
MODULE = Path(__file__).resolve().parents[1] / "src/value_investor/strategy_book_demo_mirror.py"
FORWARD = Path(__file__).resolve().parents[1] / ".github/workflows/strategy-book-forward.yml"
EMAIL = Path(__file__).resolve().parents[1] / ".github/workflows/email-report.yml"
CLIENT = Path(__file__).resolve().parents[1] / "src/value_investor/t212_client.py"


class FakeTransport:
    """In-memory demo host. ``base`` defaults to the practice origin."""

    def __init__(self, base: str = DEMO_BASE) -> None:
        self.base = base
        self.calls = 0
        self.market_calls = 0
        self.market_orders: list[dict] = []
        self.market_fail: Exception | None = None
        self.placed: list[dict] = []
        self.cancelled: list = []
        self.pending: list[dict] = []
        self.history: list[dict] = []
        self.dividends: list[dict] = []
        self.transactions: list[dict] = []
        self.position_rows: list[dict] = []
        self.summary: dict = {"currency": "GBP", "id": 1}
        self.fail: Exception | None = None
        self.place_status = "NEW"
        self.place_id = 11
        self.on_place = None

    def account_summary(self) -> dict:
        return dict(self.summary)

    def pending_orders(self) -> list[dict]:
        return list(self.pending)

    def positions(self) -> list[dict]:
        return list(self.position_rows)

    def history_orders(self) -> list[dict]:
        return list(self.history)

    def history_dividends(self) -> list[dict]:
        return list(self.dividends)

    def history_transactions(self) -> list[dict]:
        return list(self.transactions)

    def cancel(self, order_id: object) -> dict:
        self.cancelled.append(order_id)
        return {"id": order_id}

    def place_limit(self, body: dict) -> dict:
        self.calls += 1
        if self.on_place is not None:
            self.on_place(body)
        if self.fail is not None:
            raise self.fail
        self.placed.append(body)
        side = "BUY" if float(body["quantity"]) > 0 else "SELL"
        return {
            "id": self.place_id,
            "status": self.place_status,
            "ticker": body["ticker"],
            "quantity": body["quantity"],
            "limitPrice": body["limitPrice"],
            "side": side,
            "filledQuantity": 0,
        }

    def place_market(self, body: dict) -> dict:
        self.market_calls += 1
        if self.on_place is not None:
            self.on_place(body)
        if self.market_fail is not None:
            raise self.market_fail
        self.market_orders.append(body)
        return {
            "id": 77,
            "status": "FILLED",
            "type": "MARKET",
            "ticker": body["ticker"],
            "quantity": body["quantity"],
            "side": "SELL",
            "filledQuantity": abs(float(body["quantity"])),
        }


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _chart(root: Path, ticker: str, close: float = 4066.0, last: str = SIGNAL) -> None:
    _write(
        root / "docs/data/charts" / f"{ticker}.json",
        {
            "ticker": ticker,
            "currency": "GBP",
            "as_of": "2026-11-10T19:00:00+00:00",
            "dates": ["2026-11-09", last],
            "closes": [100.0, close],
        },
    )


def _overlay(root: Path, rows: list[dict]) -> None:
    _write(root / "docs/data/library/t212_coverage/by_market/ftse350.json", {"rows": rows})


def _hit(
    ticker: str,
    t212: str = "FOURl_EQ",
    currency: str = "GBX",
    *,
    basis: str = "catalogue_hit",
    tradable: bool = True,
) -> dict:
    return {
        "ticker": ticker,
        "t212_ticker": t212,
        "t212_currency": currency,
        "basis": basis,
        "tradable_on_t212": tradable,
        "updated_at": "2026-11-09",
    }


def _observe(root: Path, events: list[dict], episodes: list[dict] | None = None) -> None:
    _write(
        root / "docs/data/strategy_book_observe.json",
        {
            "registration_id": "owner-strategy-book-v0",
            "influences_live": False,
            "data_commit": "abc123",
            "generated_at": "2026-11-11T09:04:15+00:00",
            "events": events,
            "episodes": episodes or [],
        },
    )


def _pending(ticker: str, column: str = "primary") -> dict:
    return {
        "kind": "pending_fill",
        "market": "ftse350",
        "ticker": ticker,
        "column": column,
        "session": SIGNAL,
        "currency": "GBP",
    }


def _world(root: Path) -> None:
    _overlay(
        root,
        [
            _hit("FOUR.L", "FOURl_EQ"),
            _hit("MEGP.L", "PHTMl_EQ"),
            _hit("CKN.L", "CKNl_EQ"),
            _hit("NONE.L", "NONEl_EQ", basis="not_listed", tradable=False),
        ],
    )
    _chart(root, "FOUR.L", 4066.0)
    _chart(root, "MEGP.L", 103.4)
    _chart(root, "CKN.L", 50.0)
    _chart(root, "NONE.L", 10.0)
    _observe(
        root,
        [
            _pending("FOUR.L"),
            _pending("CKN.L", "decline_rejected_shadow"),
            _pending("NONE.L"),
        ],
        [
            {
                "episode_id": "ftse350:MEGP.L:primary:2026-11-10",
                "market": "ftse350",
                "ticker": "MEGP.L",
                "column": "primary",
                "status": "open",
                "currency": "GBP",
                "signal_session": SIGNAL,
                "pending_exit": True,
                "exit_signal_session": SIGNAL,
                "t212_listed": True,
                "stake": 100,
            }
        ],
    )


def _by_ticker(plans: list[dict]) -> dict[str, dict]:
    return {str(plan["ticker"]): plan for plan in plans}


def test_strategy_book_demo_plans_entry_exit_unlisted_and_non_primary(tmp_path: Path) -> None:
    _world(tmp_path)
    ledger = {
        "ledger": [
            {
                "event_id": "fill:1",
                "type": "fill",
                "t212_ticker": "PHTMl_EQ",
                "side": "BUY",
                "quantity": 2.5,
                "price": 103.4,
                "fill_id": 1,
            }
        ]
    }
    observe = json.loads(
        (tmp_path / "docs/data/strategy_book_observe.json").read_text(encoding="utf-8")
    )
    plans = build_plans(tmp_path, observe, NOW)
    attach_exit_quantities(plans, list(ledger["ledger"]))
    rows = _by_ticker(plans)
    entry = rows["FOUR.L"]
    assert entry["action"] == "would_place"
    assert entry["side"] == "BUY"
    assert entry["t212_ticker"] == "FOURl_EQ"
    assert entry["limit_price"] == 4066.0
    assert entry["limit_currency"] == "GBX"
    assert entry["quantity"] == 2.4594
    assert entry["time_validity"] == "GOOD_TILL_CANCEL"
    assert entry["fill_session"] == "2026-11-11"
    assert entry["observe_data_commit"] == "abc123"
    assert entry["influences_live"] is False
    assert entry["price_basis"] == "signal_session_chart_close_as_instrument_currency"

    exit_row = rows["MEGP.L"]
    assert exit_row["action"] == "would_place"
    assert exit_row["side"] == "SELL"
    assert exit_row["leg"] == "exit"
    assert exit_row["quantity"] == 2.5
    assert exit_row["t212_ticker"] == "PHTMl_EQ"

    assert rows["CKN.L"]["action"] == "not_mirrored"
    assert rows["CKN.L"]["reason"] == "not_primary"
    assert rows["NONE.L"]["action"] == "not_mirrored"
    assert rows["NONE.L"]["reason"] == "not_listed"


def test_strategy_book_demo_dry_run_without_key_writes_would_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _world(tmp_path)
    monkeypatch.delenv(DEMO_KEY_ENV, raising=False)
    monkeypatch.delenv(DEMO_SECRET_ENV, raising=False)
    monkeypatch.setenv("TRADING212_API_KEY", "live-key")
    monkeypatch.setenv("TRADING212_API_SECRET", "live-secret")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("demo transport must not be built on a dry run")

    monkeypatch.setattr(
        "value_investor.strategy_book_demo_mirror.DemoTransport.__init__",
        boom,
    )
    store = run_mirror(repo_root=tmp_path, now=NOW, apply=True, place=False)
    assert store["placement"] == "dry_run"
    assert store["demo_credentials_present"] is False
    assert store["influences_live"] is False
    assert store["orders_sent"] == 0
    assert store["base_url"] == DEMO_BASE
    assert any(plan["action"] == "would_place" for plan in store["plans"])
    assert store["reconciliation"]["status"] == "skipped"
    saved = json.loads(
        (tmp_path / "docs/data/strategy_book_demo_ledger.json").read_text(encoding="utf-8")
    )
    assert saved["plans"][0]["observe_data_commit"] == "abc123"


def test_strategy_book_demo_refuses_live_host_and_ignores_live_secrets(
    tmp_path: Path,
) -> None:
    with pytest.raises(DemoMirrorSafetyError):
        demo_base_url(LIVE_BASE)
    with pytest.raises(DemoMirrorSafetyError):
        demo_base_url("https://demo.trading212.com.evil.example")
    with pytest.raises(DemoMirrorSafetyError):
        demo_base_url("http://demo.trading212.com")
    assert demo_base_url(None) == DEMO_BASE
    assert demo_base_url(DEMO_BASE + "/") == DEMO_BASE

    source = MODULE.read_text(encoding="utf-8")
    assert "TRADING212_API_KEY" not in source
    assert "TRADING212_API_SECRET" not in source
    workflow = FORWARD.read_text(encoding="utf-8")
    assert "TRADING212_API_KEY" not in workflow
    assert "TRADING212_DEMO_API_KEY" in workflow
    assert "docs/data/strategy_book_demo_ledger.json" in workflow
    assert "docs/data/strategy_book_demo_ledger.json" in EMAIL.read_text(encoding="utf-8")
    assert "Does not place orders" in CLIENT.read_text(encoding="utf-8")

    seen: list[str] = []

    class Spy(dict):
        def get(self, key: str, default: object = None) -> object:
            seen.append(key)
            return super().get(key, default)

    env = Spy(
        {
            "TRADING212_API_KEY": "live-key",
            "TRADING212_API_SECRET": "live-secret",
            DEMO_KEY_ENV: "",
            DEMO_SECRET_ENV: "",
        }
    )
    assert demo_credentials(env) is None
    assert seen == [DEMO_KEY_ENV, DEMO_SECRET_ENV]

    _world(tmp_path)
    live = FakeTransport(base=LIVE_BASE)
    with pytest.raises(DemoMirrorSafetyError):
        run_mirror(
            repo_root=tmp_path,
            now=NOW,
            apply=False,
            place=True,
            transport=live,
            env={DEMO_KEY_ENV: "demo-key", DEMO_SECRET_ENV: "demo-secret"},
        )
    assert live.calls == 0

    with pytest.raises(DemoMirrorSafetyError):
        _RefuseRedirect().redirect_request(
            None,
            None,
            302,
            "Found",
            {},
            "https://live.trading212.com/api/v0/equity/orders/limit",
        )


def _seed_exit_shares(root: Path) -> None:
    _write(
        root / "docs/data/strategy_book_demo_ledger.json",
        {
            "orders": [],
            "plans": [],
            "fills": [],
            "ledger": [
                {
                    "event_id": "fill:1",
                    "type": "fill",
                    "t212_ticker": "PHTMl_EQ",
                    "side": "BUY",
                    "quantity": 2.5,
                    "price": 103.4,
                    "fill_id": 1,
                }
            ],
        },
    )


def test_strategy_book_demo_idempotent_rerun_and_submitting_checkpoint(tmp_path: Path) -> None:
    _world(tmp_path)
    _seed_exit_shares(tmp_path)
    fake = FakeTransport()
    seen: list[str] = []

    def on_place(body: dict) -> None:
        saved = json.loads(
            (tmp_path / "docs/data/strategy_book_demo_ledger.json").read_text(encoding="utf-8")
        )
        match = [row for row in saved["orders"] if row.get("t212_ticker") == body["ticker"]]
        seen.append(str(match[-1]["status"]))

    fake.on_place = on_place
    env = {DEMO_KEY_ENV: "demo-key", DEMO_SECRET_ENV: "demo-secret"}
    first = run_mirror(
        repo_root=tmp_path,
        now=NOW,
        apply=True,
        place=True,
        transport=fake,
        env=env,
        min_interval_s=0,
    )
    assert fake.calls == 2  # entry and exit
    assert seen == ["submitting", "submitting"]
    assert first["orders_sent"] == 2
    assert {row["status"] for row in first["orders"]} == {"placed"}
    buy = next(row for row in fake.placed if row["quantity"] > 0)
    sell = next(row for row in fake.placed if row["quantity"] < 0)
    assert buy["timeValidity"] == "GOOD_TILL_CANCEL"
    assert buy["ticker"] == "FOURl_EQ"
    assert buy["quantity"] == 2.4594
    assert buy["limitPrice"] == 4066.0
    assert sell["quantity"] == -2.5
    assert sell["ticker"] == "PHTMl_EQ"

    second = run_mirror(
        repo_root=tmp_path,
        now=NOW,
        apply=True,
        place=True,
        transport=fake,
        env=env,
        min_interval_s=0,
    )
    assert fake.calls == 2
    assert second["orders_sent"] == 0
    working = [plan for plan in second["plans"] if plan["ticker"] in {"FOUR.L", "MEGP.L"}]
    assert {plan["action"] for plan in working} == {"placed"}


def test_strategy_book_demo_rejection_is_not_retried(tmp_path: Path) -> None:
    _world(tmp_path)
    _seed_exit_shares(tmp_path)
    fake = FakeTransport()
    fake.fail = DemoOrderRejected(400, "quantity rejected")
    env = {DEMO_KEY_ENV: "k", DEMO_SECRET_ENV: "s"}
    store = run_mirror(
        repo_root=tmp_path,
        now=NOW,
        apply=True,
        place=True,
        transport=fake,
        env=env,
        min_interval_s=0,
    )
    assert fake.calls == 2
    assert store["orders_sent"] == 0
    assert {row["status"] for row in store["orders"]} == {"rejected"}
    run_mirror(
        repo_root=tmp_path,
        now=NOW,
        apply=True,
        place=True,
        transport=fake,
        env=env,
        min_interval_s=0,
    )
    assert fake.calls == 2


def _run(root: Path, fake: object, now: datetime = NOW) -> dict:
    return run_mirror(
        repo_root=root,
        now=now,
        apply=True,
        place=True,
        transport=fake,
        env={DEMO_KEY_ENV: "k", DEMO_SECRET_ENV: "s"},
        min_interval_s=0,
    )


def test_strategy_book_demo_submit_unknown_is_resent_only_without_any_trace(
    tmp_path: Path,
) -> None:
    _world(tmp_path)
    _seed_exit_shares(tmp_path)
    fake = FakeTransport()
    fake.fail = DemoTransportError("HTTP 502: bad gateway")
    store = _run(tmp_path, fake)
    assert {row["status"] for row in store["orders"]} == {"submit_unknown"}
    assert {row["detail"] for row in store["orders"]} == {
        "DemoTransportError: HTTP 502: bad gateway"
    }
    fake.fail = None

    def pending_down() -> list[dict]:
        raise DemoTransportError("HTTP 429: slow down")

    fake.pending_orders = pending_down  # type: ignore[method-assign]
    _run(tmp_path, fake)
    assert fake.calls == 2

    del fake.pending_orders
    fake.history = [{"order": {"ticker": "PHTMl_EQ", "side": "SELL", "status": "CANCELLED"}}]
    store = _run(tmp_path, fake)
    assert fake.calls == 3
    orders = {row["t212_ticker"]: row for row in store["orders"]}
    assert orders["FOURl_EQ"]["status"] == "placed"
    assert orders["FOURl_EQ"]["quantity"] == 2.4594
    assert orders["PHTMl_EQ"]["status"] == "submit_unknown"
    assert fake.placed[-1]["ticker"] == "FOURl_EQ"


def test_strategy_book_demo_submit_unknown_adopts_a_pending_order(tmp_path: Path) -> None:
    _world(tmp_path)
    _seed_exit_shares(tmp_path)
    fake = FakeTransport()
    fake.fail = DemoTransportError("timeout")
    _run(tmp_path, fake)
    fake.fail = None
    fake.pending = [
        {
            "id": 501,
            "ticker": "FOURl_EQ",
            "side": "BUY",
            "quantity": 2.4594,
            "limitPrice": 4066.0,
            "status": "NEW",
        }
    ]
    fake.history = [
        {
            "order": {"ticker": "PHTMl_EQ", "side": "SELL", "id": 502},
            "fill": {"id": 9, "quantity": 2.5, "price": 104.0, "filledAt": "2026-11-11T11:00:00Z"},
        }
    ]
    store = _run(tmp_path, fake)
    assert fake.calls == 2
    orders = {row["t212_ticker"]: row for row in store["orders"]}
    assert orders["FOURl_EQ"]["status"] == "placed"
    assert orders["FOURl_EQ"]["broker_order_id"] == 501
    assert orders["PHTMl_EQ"]["status"] == "filled"
    assert orders["PHTMl_EQ"]["broker_order_id"] == 502


def _precision_gate(allowed: int):
    def on_place(body: dict) -> None:
        text = repr(abs(float(body["quantity"])))
        decimals = len(text.split(".", 1)[1]) if "." in text else 0
        if decimals > allowed:
            raise DemoOrderRejected(
                400,
                json.dumps(
                    {
                        "type": "/api-errors/quantity-precision-mismatch",
                        "title": "Error while placing the order",
                        "status": 400,
                        "detail": f"invalid quantity precision {allowed}",
                    }
                ),
            )

    return on_place


def test_strategy_book_demo_precision_rejection_retries_once_floored(tmp_path: Path) -> None:
    _world(tmp_path)
    _seed_exit_shares(tmp_path)
    fake = FakeTransport()
    fake.on_place = _precision_gate(3)
    store = _run(tmp_path, fake)
    orders = {row["t212_ticker"]: row for row in store["orders"]}
    four = orders["FOURl_EQ"]
    assert four["status"] == "placed"
    assert four["quantity"] == 2.459
    assert four["quantity_requested"] == 2.4594
    assert four["precision_retried"] is True
    assert [row["quantity"] for row in fake.placed if row["ticker"] == "FOURl_EQ"] == [2.459]
    assert _by_ticker(store["plans"])["FOUR.L"]["quantity"] == 2.459
    assert orders["PHTMl_EQ"]["status"] == "placed"

    fake.on_place = _precision_gate(0)
    tight = tmp_path / "tight"
    _world(tight)
    store = _run(tight, fake)
    four = {row["t212_ticker"]: row for row in store["orders"]}["FOURl_EQ"]
    assert four["status"] == "rejected"
    assert four["precision_retried"] is True
    calls = fake.calls
    _run(tight, fake)
    assert fake.calls == calls


def test_strategy_book_demo_precision_rejected_before_the_fix_is_resent(tmp_path: Path) -> None:
    _world(tmp_path)
    detail = json.dumps(
        {
            "type": "/api-errors/quantity-precision-mismatch",
            "status": 400,
            "detail": "invalid quantity precision 3",
        }
    )
    ref = "sbdemo:ftse350:FOUR.L:primary:2026-11-10:entry"
    _write(
        tmp_path / "docs/data/strategy_book_demo_ledger.json",
        {
            "orders": [
                {
                    "client_order_ref": ref,
                    "episode_id": "ftse350:FOUR.L:primary:2026-11-10",
                    "leg": "entry",
                    "order_type": "LIMIT",
                    "market": "ftse350",
                    "ticker": "FOUR.L",
                    "t212_ticker": "FOURl_EQ",
                    "side": "BUY",
                    "quantity": 2.4594,
                    "limit_price": 4066.0,
                    "fill_session": "2026-11-11",
                    "status": "rejected",
                    "broker_status": 400,
                    "detail": detail,
                }
            ],
            "plans": [
                {
                    "client_order_ref": ref,
                    "ticker": "FOUR.L",
                    "action": "rejected",
                    "reason": "rejected",
                    "market": "ftse350",
                    "fill_session": "2026-11-11",
                }
            ],
            "fills": [],
            "ledger": [],
        },
    )
    fake = FakeTransport()
    fake.on_place = _precision_gate(3)
    store = _run(tmp_path, fake)
    four = {row["t212_ticker"]: row for row in store["orders"]}["FOURl_EQ"]
    assert four["status"] == "placed"
    assert four["quantity"] == 2.459
    assert _by_ticker(store["plans"])["FOUR.L"]["action"] == "placed"


def test_strategy_book_demo_rate_limited_send_is_retried_next_run(tmp_path: Path) -> None:
    _world(tmp_path)
    _seed_exit_shares(tmp_path)
    fake = FakeTransport()
    fake.fail = DemoRateLimited("HTTP 429: too many requests")
    store = _run(tmp_path, fake)
    assert {row["status"] for row in store["orders"]} == {"rate_limited"}
    plans = _by_ticker(store["plans"])
    assert plans["FOUR.L"]["action"] == "would_place"
    assert plans["FOUR.L"]["reason"] == "rate_limited"
    fake.fail = None
    store = _run(tmp_path, fake)
    assert {row["status"] for row in store["orders"]} == {"placed"}
    assert len(fake.placed) == 2


def _transport(responses: list, sleeps: list[float], min_interval_s: float = 0) -> DemoTransport:
    queue = list(responses)
    seen: list[str] = []

    def opener(req: object) -> tuple:
        seen.append(f"{req.get_method()} {req.full_url}")  # type: ignore[attr-defined]
        return queue.pop(0)

    transport = DemoTransport(
        env={DEMO_KEY_ENV: "k", DEMO_SECRET_ENV: "s"},
        opener=opener,
        min_interval_s=min_interval_s,
        sleep=sleeps.append,
    )
    transport.seen = seen  # type: ignore[attr-defined]
    return transport


def test_strategy_book_demo_transport_waits_out_429_then_gives_up() -> None:
    sleeps: list[float] = []
    transport = _transport([(429, "{}", 3.0), (429, "{}", None), (200, "[]")], sleeps)
    assert transport.pending_orders() == []
    assert sleeps == [3.0, 5.0]

    sleeps.clear()
    transport = _transport([(429, "{}", 120.0)] * 4, sleeps)
    with pytest.raises(DemoRateLimited):
        transport.place_limit({"ticker": "FOURl_EQ", "quantity": 1.0, "limitPrice": 1.0})
    assert sleeps == [30.0, 30.0, 30.0]
    assert len(transport.seen) == 4  # type: ignore[attr-defined]


def test_strategy_book_demo_transport_paces_each_endpoint() -> None:
    sleeps: list[float] = []
    transport = _transport(
        [(200, '{"currency": "GBP"}'), (200, "[]"), (200, "[]"), (200, "[]")],
        sleeps,
        min_interval_s=2.0,
    )
    transport.account_summary()
    transport.pending_orders()
    assert sleeps == []
    transport.pending_orders()
    assert len(sleeps) == 1 and 5.0 < sleeps[0] <= 5.25
    transport.positions()
    assert len(sleeps) == 1


def test_strategy_book_demo_partial_fill_dividend_split_and_cancel(tmp_path: Path) -> None:
    _overlay(tmp_path, [_hit("FOUR.L")])
    _chart(tmp_path, "FOUR.L", 4066.0)
    _observe(tmp_path, [_pending("FOUR.L")])
    fake = FakeTransport()
    fake.place_status = "PARTIALLY_FILLED"
    fake.history = [
        {
            "order": {
                "id": 11,
                "ticker": "FOURl_EQ",
                "side": "BUY",
                "status": "PARTIALLY_FILLED",
                "currency": "GBX",
                "instrument": {"ticker": "FOURl_EQ", "currency": "GBX"},
            },
            "fill": {
                "id": 42,
                "price": 4000.0,
                "quantity": 1.0,
                "filledAt": "2026-11-11T15:00:00Z",
                "type": "TRADE",
                "walletImpact": {
                    "netValue": -40.5,
                    "currency": "GBP",
                    "taxes": [{"name": "STAMP_DUTY", "quantity": 0.2, "currency": "GBP"}],
                },
            },
        },
        {
            "order": {
                "id": 11,
                "ticker": "FOURl_EQ",
                "side": "BUY",
                "status": "PARTIALLY_FILLED",
                "currency": "GBX",
            },
            "fill": {
                "id": 43,
                "price": 0,
                "quantity": 1.0,
                "filledAt": "2026-11-12T08:00:00Z",
                "type": "STOCK_SPLIT",
            },
        },
    ]
    fake.dividends = [
        {
            "reference": "DIV1",
            "amount": 1.25,
            "currency": "GBP",
            "paidOn": "2026-11-12T00:00:00Z",
            "ticker": "FOURl_EQ",
            "type": "ORDINARY",
        }
    ]
    fake.transactions = [
        {
            "reference": "DEP1",
            "amount": 1000.0,
            "currency": "GBP",
            "type": "DEPOSIT",
            "dateTime": "2026-11-01T00:00:00Z",
        }
    ]
    fake.position_rows = [
        {"ticker": "FOURl_EQ", "quantity": 2.0, "instrument": {"ticker": "FOURl_EQ"}}
    ]
    env = {DEMO_KEY_ENV: "k", DEMO_SECRET_ENV: "s"}
    store = run_mirror(
        repo_root=tmp_path,
        now=NOW,
        apply=True,
        place=True,
        transport=fake,
        env=env,
        min_interval_s=0,
    )
    kinds = {event["type"] for event in store["ledger"]}
    assert {"fill", "split", "dividend", "transaction"} <= kinds
    fill = next(event for event in store["ledger"] if event["type"] == "fill")
    assert fill["price"] == 4000.0
    assert fill["taxes"][0]["name"] == "STAMP_DUTY"
    assert fill["slippage"]["status"] == "insufficient_data"
    assert store["reconciliation"]["status"] == "match"
    assert store["slippage"]["measured_count"] == 0

    again = run_mirror(
        repo_root=tmp_path,
        now=NOW,
        apply=True,
        place=True,
        transport=fake,
        env=env,
        min_interval_s=0,
    )
    assert sum(1 for event in again["ledger"] if event["type"] == "dividend") == 1
    assert sum(1 for event in again["ledger"] if event["type"] == "split") == 1

    fake.pending = [{"id": 11}]
    cancelled = run_mirror(
        repo_root=tmp_path,
        now=AFTER_CLOSE,
        apply=True,
        place=True,
        transport=fake,
        env=env,
        min_interval_s=0,
    )
    assert fake.cancelled == [11]
    assert any(row.get("remainder_cancelled") for row in cancelled["orders"])
    assert any(row["status"] == "partial" for row in cancelled["orders"])


def test_strategy_book_demo_cancels_unfilled_order_after_the_close(tmp_path: Path) -> None:
    _overlay(tmp_path, [_hit("FOUR.L")])
    _chart(tmp_path, "FOUR.L")
    _observe(tmp_path, [_pending("FOUR.L")])
    fake = FakeTransport()
    env = {DEMO_KEY_ENV: "k", DEMO_SECRET_ENV: "s"}
    run_mirror(
        repo_root=tmp_path,
        now=NOW,
        apply=True,
        place=True,
        transport=fake,
        env=env,
        min_interval_s=0,
    )
    fake.pending = [{"id": 11}]
    cancelled = run_mirror(
        repo_root=tmp_path,
        now=AFTER_CLOSE,
        apply=True,
        place=True,
        transport=fake,
        env=env,
        min_interval_s=0,
    )
    assert fake.cancelled == [11]
    assert cancelled["orders"][0]["status"] == "cancelled"
    assert fake.calls == 1
    assert fake.market_calls == 0


def test_strategy_book_demo_reconciliation_mismatch_and_delisting() -> None:
    events = [
        {
            "event_id": "fill:7",
            "type": "fill",
            "t212_ticker": "FOURl_EQ",
            "side": "BUY",
            "quantity": 1.0,
            "price": 4066.0,
            "fill_id": 7,
            "cash": {"currency": "GBP", "net_value": -40.0},
        }
    ]
    note_delistings(events, [])
    assert events[-1]["type"] == "delisting"
    assert events[-1]["cash"] is None
    mismatch = reconcile(
        events,
        {
            "positions": [{"ticker": "FOURl_EQ", "quantity": 5}],
            "history_orders": [],
            "dividends": [],
            "transactions": [],
            "gaps": [],
        },
    )
    assert mismatch["status"] == "mismatch"
    missing = reconcile(
        events,
        {
            "positions": None,
            "history_orders": [],
            "dividends": [],
            "transactions": [],
            "gaps": [],
        },
    )
    assert missing["status"] == "insufficient_data"
    assert not any(diff["kind"] == "position" for diff in missing["diffs"])


def test_strategy_book_demo_slippage_and_order_cap() -> None:
    buy = compute_slippage(book_price=100.0, raw_price=100.5, side="BUY", half_spread=0.00025)
    assert buy["status"] == "measured"
    assert buy["slippage_pct"] == pytest.approx(0.005)
    assert buy["vs_half_spread"] == pytest.approx(0.005 - 0.00025)
    sell = compute_slippage(book_price=100.0, raw_price=99.0, side="SELL", half_spread=0.00025)
    assert sell["slippage_pct"] == pytest.approx(0.01)
    assert compute_slippage(book_price=None, raw_price=1, side="BUY", half_spread=0)["status"] == (
        "insufficient_data"
    )

    plans = [
        {"action": "would_place", "leg": "entry", "ticker": f"T{i}", "client_order_ref": f"r{i}"}
        for i in range(ORDER_CAP + 1)
    ]
    used = apply_order_cap(plans, order_cap=10_000)
    assert used == ORDER_CAP
    assert sum(plan["action"] == "would_place" for plan in plans) == ORDER_CAP
    assert sum(plan.get("reason") == "order_cap" for plan in plans) == 1


def test_strategy_book_demo_account_currency_and_place_without_apply(tmp_path: Path) -> None:
    _overlay(tmp_path, [_hit("FOUR.L")])
    _chart(tmp_path, "FOUR.L")
    _observe(tmp_path, [_pending("FOUR.L")])
    fake = FakeTransport()
    fake.summary = {"currency": "USD", "id": 1}
    env = {DEMO_KEY_ENV: "k", DEMO_SECRET_ENV: "s"}
    blocked = run_mirror(
        repo_root=tmp_path,
        now=NOW,
        apply=True,
        place=True,
        transport=fake,
        env=env,
        min_interval_s=0,
    )
    assert fake.calls == 0
    assert blocked["plans"][0]["reason"] == "account_currency"

    refused = run_mirror(
        repo_root=tmp_path,
        now=NOW,
        apply=False,
        place=True,
        transport=FakeTransport(),
        env=env,
        min_interval_s=0,
    )
    assert refused["placement"] == "skipped_place_requires_apply"
    assert refused["orders"] == []


def test_strategy_book_demo_does_not_backfill_an_open_primary(tmp_path: Path) -> None:
    _overlay(tmp_path, [_hit("FOUR.L")])
    _chart(tmp_path, "FOUR.L")
    _observe(
        tmp_path,
        [_pending("FOUR.L")],
        [
            {
                "episode_id": "ftse350:FOUR.L:primary:2026-11-10",
                "market": "ftse350",
                "ticker": "FOUR.L",
                "column": "primary",
                "status": "open",
                "signal_session": SIGNAL,
                "t212_listed": True,
            }
        ],
    )
    fake = FakeTransport()
    store = run_mirror(
        repo_root=tmp_path,
        now=NOW,
        apply=True,
        place=True,
        transport=fake,
        env={DEMO_KEY_ENV: "k", DEMO_SECRET_ENV: "s"},
        min_interval_s=0,
    )
    assert store["plans"][0]["reason"] == "already_open"
    assert store["plans"][0]["action"] == "not_mirrored"
    assert fake.calls == 0


def test_strategy_book_demo_stale_quote_and_missed_session(tmp_path: Path) -> None:
    _overlay(tmp_path, [_hit("FOUR.L")])
    _chart(tmp_path, "FOUR.L", last="2026-11-09")
    _observe(tmp_path, [_pending("FOUR.L")])
    observe = json.loads(
        (tmp_path / "docs/data/strategy_book_observe.json").read_text(encoding="utf-8")
    )
    stale = build_plans(tmp_path, observe, NOW)
    assert stale[0]["reason"] == "stale_quote"
    _chart(tmp_path, "FOUR.L", last=SIGNAL)
    missed = build_plans(tmp_path, observe, AFTER_CLOSE)
    assert missed[0]["reason"] == "missed_fill_session"


def test_strategy_book_demo_ops_monitor_findings(tmp_path: Path) -> None:
    from value_investor.ops_monitor import check_strategy_book_demo_mirror

    missing = check_strategy_book_demo_mirror(repo_root=tmp_path)
    assert [row.title for row in missing] == [TITLE_NOT_CONFIGURED]
    assert missing[0].auto_fixable is False
    assert missing[0].severity == "info"

    ledger_path = tmp_path / "docs/data/strategy_book_demo_ledger.json"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text("{", encoding="utf-8")
    broken = check_strategy_book_demo_mirror(repo_root=tmp_path)
    assert broken[0].title == TITLE_MISMATCH
    assert broken[0].severity == "warn"
    assert broken[0].auto_fixable is False

    payload = {
        "demo_credentials_present": True,
        "summary": {"orders_sent": 2, "would_place": 0},
        "orders_sent": 2,
        "reconciliation": {"status": "mismatch", "diffs": [{"kind": "position"}]},
        "fills": [
            {"slippage": {"status": "measured", "slippage_pct": 0.001}},
            {"slippage": {"status": "measured", "slippage_pct": 0.002}},
            {"slippage": {"status": "measured", "slippage_pct": 0.003}},
        ],
    }
    rows = findings_from_ledger(payload)
    assert {row["title"] for row in rows} == {TITLE_ORDERS_PLACED, TITLE_MISMATCH, TITLE_SLIPPAGE}
    assert all(row["auto_fixable"] is False for row in rows)
    ledger_path.write_text(json.dumps(payload), encoding="utf-8")
    checked = check_strategy_book_demo_mirror(repo_root=tmp_path)
    assert all(row.auto_fixable is False for row in checked)
    assert {row.title for row in checked} == {TITLE_ORDERS_PLACED, TITLE_MISMATCH, TITLE_SLIPPAGE}


def test_strategy_book_demo_cli_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _overlay(tmp_path, [_hit("FOUR.L")])
    _chart(tmp_path, "FOUR.L")
    _observe(tmp_path, [_pending("FOUR.L")])
    code = main(["--repo-root", str(tmp_path), "--as-of", "2026-11-11T10:00:00+00:00"])
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["placement"] == "dry_run"
    assert printed["would_place"] == 1
    assert printed["influences_live"] is False


def test_strategy_book_demo_ingest_matches_statement() -> None:
    events: list[dict] = []
    fills: list[dict] = []
    statement = {
        "positions": [{"ticker": "FOURl_EQ", "quantity": 2.0}],
        "history_orders": [
            {
                "order": {"id": 11, "ticker": "FOURl_EQ", "side": "BUY", "status": "FILLED"},
                "fill": {
                    "id": 7,
                    "price": 4066,
                    "quantity": 1,
                    "filledAt": "2026-11-11T16:30:00Z",
                    "type": "TRADE",
                    "walletImpact": {"netValue": -40.66, "currency": "GBP"},
                },
            },
            {
                "order": {"id": 11, "ticker": "FOURl_EQ", "side": "BUY"},
                "fill": {
                    "id": 8,
                    "quantity": 1,
                    "filledAt": "2026-11-12T00:00:00Z",
                    "type": "STOCK_SPLIT",
                },
            },
        ],
        "dividends": [
            {
                "reference": "DIV1",
                "amount": 1.25,
                "currency": "GBP",
                "paidOn": "2026-11-12T00:00:00Z",
                "ticker": "FOURl_EQ",
            }
        ],
        "transactions": [
            {
                "reference": "DEP1",
                "amount": 100,
                "currency": "GBP",
                "type": "DEPOSIT",
                "dateTime": "2026-11-01T00:00:00Z",
            }
        ],
        "gaps": [],
    }
    orders = {
        "ref": {
            "client_order_ref": "ref",
            "episode_id": "ep",
            "leg": "entry",
            "broker_order_id": 11,
            "half_spread": 0.00025,
        }
    }
    episodes = {"ep": {"status": "open", "return_entry_fill": 4066.0}}
    gaps = ingest_statement(events, fills, statement, orders, episodes)
    assert gaps == []
    result = reconcile(events, statement)
    assert result["status"] == "match"
    assert {event["type"] for event in events} == {"fill", "split", "dividend", "transaction"}
    fill = next(event for event in events if event["type"] == "fill")
    assert fill["slippage"]["status"] == "measured"
    assert fill["slippage"]["slippage_pct"] == pytest.approx(0.0)


EPISODE = "ftse350:FOUR.L:primary:2026-11-10"
CATCH_NOW = datetime(2026, 11, 12, 18, 0, tzinfo=UTC)
ENV = {DEMO_KEY_ENV: "k", DEMO_SECRET_ENV: "s"}


def _buy_fill(quantity: float, fill_id: int = 1) -> dict:
    return {
        "event_id": f"fill:{fill_id}",
        "type": "fill",
        "episode_id": EPISODE,
        "t212_ticker": "FOURl_EQ",
        "side": "BUY",
        "quantity": quantity,
        "price": 4066.0,
        "currency": "GBX",
        "fill_id": fill_id,
    }


def _exit_order(status: str, **extra: object) -> dict:
    row = {
        "client_order_ref": f"sbdemo:{EPISODE}:exit",
        "episode_id": EPISODE,
        "leg": "exit",
        "order_type": "LIMIT",
        "status": status,
        "side": "SELL",
        "quantity": 2.5,
        "limit_price": 4066.0,
        "limit_currency": "GBX",
        "t212_ticker": "FOURl_EQ",
        "ticker": "FOUR.L",
        "market": "ftse350",
        "column": "primary",
        "fill_session": "2026-11-11",
        "broker_order_id": 11,
        "half_spread": 0.00025,
        "influences_live": False,
    }
    row.update(extra)
    return row


def _closed_episode() -> dict:
    return {
        "episode_id": EPISODE,
        "market": "ftse350",
        "ticker": "FOUR.L",
        "column": "primary",
        "status": "closed",
        "signal_session": SIGNAL,
        "exit_session": "2026-11-11",
        "exit_fill": 4100.0,
        "pending_exit": False,
        "t212_listed": True,
        "currency": "GBP",
    }


def _seed_held(root: Path, orders: list[dict], ledger: list[dict]) -> None:
    _overlay(root, [_hit("FOUR.L")])
    _chart(root, "FOUR.L")
    _observe(root, [], [_closed_episode()])
    _write(
        root / "docs/data/strategy_book_demo_ledger.json",
        {"orders": orders, "plans": [], "fills": [], "ledger": ledger},
    )


def test_strategy_book_demo_unfilled_exit_catches_up_on_the_next_run(tmp_path: Path) -> None:
    _seed_held(tmp_path, [_exit_order("placed")], [_buy_fill(2.5)])
    fake = FakeTransport()
    fake.pending = [
        {"id": 11, "ticker": "FOURl_EQ", "side": "SELL", "quantity": -2.5, "limitPrice": 4066}
    ]
    cancelled = run_mirror(
        repo_root=tmp_path,
        now=CATCH_NOW,
        apply=True,
        place=True,
        transport=fake,
        env=ENV,
        min_interval_s=0,
    )
    assert fake.market_calls == 0
    assert cancelled["orders"][0]["status"] == "cancelled"
    fake.history = [
        {
            "order": {
                "id": 77,
                "ticker": "FOURl_EQ",
                "side": "SELL",
                "status": "FILLED",
                "currency": "GBX",
            },
            "fill": {
                "id": 90,
                "price": 4200.0,
                "quantity": 2.5,
                "filledAt": "2026-11-12T16:35:00Z",
                "type": "TRADE",
                "walletImpact": {"netValue": 105.0, "currency": "GBP"},
            },
        }
    ]
    caught = run_mirror(
        repo_root=tmp_path,
        now=CATCH_NOW,
        apply=True,
        place=True,
        transport=fake,
        env=ENV,
        min_interval_s=0,
    )
    assert fake.market_calls == 1
    assert fake.market_orders == [{"ticker": "FOURl_EQ", "quantity": -2.5}]
    plan = next(row for row in caught["plans"] if row["leg"] == "exit_catchup")
    assert plan["client_order_ref"] == f"sbdemo:{EPISODE}:exit_catchup"
    assert plan["reason"] == "unfilled_exit"
    assert plan["sessions_late"] == 1
    assert plan["order_type"] == "MARKET"
    fill = next(row for row in caught["ledger"] if row.get("timing") == "catchup")
    assert fill["slippage"]["status"] == "measured"
    assert fill["slippage"]["slippage_pct"] == pytest.approx(1 - 4200.0 / 4100.0)
    assert fill["sessions_late"] == 1
    assert caught["slippage"]["catchup_count"] == 1
    assert caught["slippage"]["on_time_count"] == 0
    again = run_mirror(
        repo_root=tmp_path,
        now=CATCH_NOW,
        apply=True,
        place=True,
        transport=fake,
        env=ENV,
        min_interval_s=0,
    )
    assert fake.market_calls == 1
    assert again["orders_sent"] == 0


def test_strategy_book_demo_partial_exit_catches_up_the_remainder_only(tmp_path: Path) -> None:
    sell = _buy_fill(1.0, fill_id=2)
    sell["side"] = "SELL"
    sell["event_id"] = "fill:2"
    _seed_held(
        tmp_path,
        [_exit_order("partial", remainder_cancelled=False)],
        [_buy_fill(2.5), sell],
    )
    fake = FakeTransport()
    fake.pending = [{"id": 11}]
    run_mirror(
        repo_root=tmp_path,
        now=CATCH_NOW,
        apply=True,
        place=True,
        transport=fake,
        env=ENV,
        min_interval_s=0,
    )
    assert fake.market_calls == 0
    assert fake.cancelled == [11]
    caught = run_mirror(
        repo_root=tmp_path,
        now=CATCH_NOW,
        apply=True,
        place=True,
        transport=fake,
        env=ENV,
        min_interval_s=0,
    )
    assert fake.market_orders == [{"ticker": "FOURl_EQ", "quantity": -1.5}]
    plan = next(row for row in caught["plans"] if row["leg"] == "exit_catchup")
    assert plan["reason"] == "unfilled_exit"
    assert plan["quantity"] == 1.5


def test_strategy_book_demo_closed_episode_without_exit_order_catches_up(tmp_path: Path) -> None:
    _seed_held(tmp_path, [], [_buy_fill(2.0)])
    fake = FakeTransport()
    store = run_mirror(
        repo_root=tmp_path,
        now=CATCH_NOW,
        apply=True,
        place=True,
        transport=fake,
        env=ENV,
        min_interval_s=0,
    )
    assert fake.market_orders == [{"ticker": "FOURl_EQ", "quantity": -2.0}]
    plan = next(row for row in store["plans"] if row["leg"] == "exit_catchup")
    assert plan["reason"] == "missed_exit_order"
    assert plan["sessions_late"] == 1
    assert fake.calls == 0


def test_strategy_book_demo_catchup_stuck_after_five_rejections(tmp_path: Path) -> None:
    from value_investor.ops_monitor import check_strategy_book_demo_mirror

    _seed_held(tmp_path, [], [_buy_fill(2.0)])
    fake = FakeTransport()
    fake.market_fail = DemoOrderRejected(400, "market closed")
    store = {}
    for _ in range(CATCHUP_ATTEMPT_LIMIT):
        store = run_mirror(
            repo_root=tmp_path,
            now=CATCH_NOW,
            apply=True,
            place=True,
            transport=fake,
            env=ENV,
            min_interval_s=0,
        )
    assert fake.market_calls == CATCHUP_ATTEMPT_LIMIT
    order = next(row for row in store["orders"] if row["leg"] == "exit_catchup")
    assert order["status"] == "rejected"
    assert order["attempt_count"] == CATCHUP_ATTEMPT_LIMIT
    titles = {row["title"]: row for row in findings_from_ledger(store)}
    assert titles[TITLE_STUCK]["severity"] == "warn"
    assert titles[TITLE_STUCK]["auto_fixable"] is False
    checked = check_strategy_book_demo_mirror(repo_root=tmp_path)
    stuck = next(row for row in checked if row.title == TITLE_STUCK)
    assert stuck.severity == "warn"
    assert stuck.auto_fixable is False
    run_mirror(
        repo_root=tmp_path,
        now=CATCH_NOW,
        apply=True,
        place=True,
        transport=fake,
        env=ENV,
        min_interval_s=0,
    )
    assert fake.market_calls == CATCHUP_ATTEMPT_LIMIT


def test_strategy_book_demo_catchup_unknown_adopts_a_fill_instead_of_resending(
    tmp_path: Path,
) -> None:
    _seed_held(tmp_path, [], [_buy_fill(2.0)])
    fake = FakeTransport()
    fake.market_fail = DemoTransportError("timeout")
    run_mirror(
        repo_root=tmp_path,
        now=CATCH_NOW,
        apply=True,
        place=True,
        transport=fake,
        env=ENV,
        min_interval_s=0,
    )
    assert fake.market_calls == 1
    fake.market_fail = None
    fake.history = [
        {
            "order": {"id": 77, "ticker": "FOURl_EQ", "side": "SELL", "status": "FILLED"},
            "fill": {
                "id": 91,
                "price": 4100.0,
                "quantity": 2.0,
                "filledAt": "2026-11-12T18:05:00Z",
                "type": "TRADE",
            },
        }
    ]
    second = run_mirror(
        repo_root=tmp_path,
        now=CATCH_NOW,
        apply=True,
        place=True,
        transport=fake,
        env=ENV,
        min_interval_s=0,
    )
    assert fake.market_calls == 1
    adopted = next(row for row in second["orders"] if row["leg"] == "exit_catchup")
    assert adopted["status"] == "filled"
    assert adopted["broker_order_id"] == 77
