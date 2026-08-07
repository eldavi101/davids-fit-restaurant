"""API contract tests, the full BUY→ACTIVE→SELL→CLOSED pipeline, and the
absence of any external notification integration."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API = "/api/v1"
KEY = {"X-API-Key": "test-key"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    from app.core.config import get_settings, get_strategy
    from app.data.providers.registry import get_provider, set_provider
    from app.db.session import init_db, reset_engine

    monkeypatch.setenv("API_KEYS", "test-key")
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "synthetic")
    monkeypatch.setenv("ENABLE_SCHEDULER", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'test.db'}")
    get_settings.cache_clear()
    get_strategy.cache_clear()
    set_provider(None)
    get_provider(force_rebuild=True)

    reset_engine(f"sqlite:///{tmp_path/'test.db'}")
    init_db()

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    reset_engine()
    get_settings.cache_clear()
    get_strategy.cache_clear()
    set_provider(None)


@pytest.fixture
def seeded(client):
    """A client whose database has a refreshed universe and one completed scan."""
    assert client.post(f"{API}/system/universe", headers=KEY).status_code == 200
    assert client.post(f"{API}/system/scan", headers=KEY).status_code == 200
    return client


# --------------------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------------------


def test_health_needs_no_key(client):
    response = client.get(f"{API}/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_every_other_endpoint_requires_a_key(client):
    for path in ("/market/status", "/scanner", "/alerts", "/positions", "/analytics", "/settings"):
        assert client.get(f"{API}{path}").status_code == 401, path


def test_a_wrong_key_is_rejected(client):
    response = client.get(f"{API}/alerts", headers={"X-API-Key": "nope"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


# --------------------------------------------------------------------------------------
# Market
# --------------------------------------------------------------------------------------


def test_market_status_declares_synthetic_data(client):
    """Requirement 61.1 — generated bars must never masquerade as real market data."""
    body = client.get(f"{API}/market/status", headers=KEY).json()
    assert body["synthetic_data"] is True
    assert body["data_provider"] == "synthetic"
    assert body["session"] in ("PRE", "OPEN", "POST", "CLOSED", "HOLIDAY")
    assert body["paper_trading"] is True


def test_market_regime_is_classified(seeded):
    body = seeded.get(f"{API}/market/regime", headers=KEY).json()
    assert body["regime"] in (
        "STRONG_BULL", "BULL", "NEUTRAL", "RISK_OFF", "BEAR", "HIGH_VOLATILITY",
    )
    assert 0 <= body["regime_score"] <= 100


# --------------------------------------------------------------------------------------
# Scanner
# --------------------------------------------------------------------------------------


def test_scanner_returns_ranked_results(seeded):
    body = seeded.get(f"{API}/scanner", headers=KEY).json()
    assert body["total"] > 0
    results = body["results"]
    assert results[0]["rank"] == 1

    scores = [r["opportunity_score"] for r in results]
    assert scores == sorted(scores, reverse=True)

    first = results[0]
    for field in ("ticker", "opportunity_score", "confidence", "category",
                  "trend_score", "momentum_score", "volume_score", "breakout_score",
                  "relative_strength_score", "fundamental_score", "risk_score",
                  "reward_risk", "rules_failed"):
        assert field in first, field
    assert first["category"] in (
        "EXCEPTIONAL", "STRONG_BUY", "BUY", "WATCH", "NEUTRAL", "AVOID",
    )


def test_scanner_filters_and_sorting(seeded):
    high = seeded.get(f"{API}/scanner", headers=KEY, params={"min_score": 99.9}).json()
    assert high["total"] == 0

    by_ticker = seeded.get(
        f"{API}/scanner", headers=KEY, params={"sort": "ticker", "order": "asc"}
    ).json()["results"]
    tickers = [r["ticker"] for r in by_ticker]
    assert tickers == sorted(tickers)

    searched = seeded.get(f"{API}/scanner", headers=KEY, params={"search": "NVDA"}).json()
    assert all("NVDA" in r["ticker"] for r in searched["results"])


def test_every_scanner_row_explains_itself(seeded):
    """Requirement 49 — a rejected stock says which rules it failed."""
    for row in seeded.get(f"{API}/scanner", headers=KEY).json()["results"]:
        if not row["signal_ready"]:
            assert row["rules_failed"], f"{row['ticker']} rejected without a reason"


# --------------------------------------------------------------------------------------
# Stocks
# --------------------------------------------------------------------------------------


def test_stock_profile_and_analysis(seeded):
    profile = seeded.get(f"{API}/stocks/NVDA", headers=KEY).json()
    assert profile["ticker"] == "NVDA"
    assert profile["eligible"] is True

    analysis = seeded.get(f"{API}/stocks/NVDA/analysis", headers=KEY).json()
    assert analysis["analysis_available"] is True
    assert "score" in analysis and "levels" in analysis
    assert "probability" in analysis
    assert analysis["probability"]["sample_size"] is not None
    assert "decision" in analysis
    assert len(analysis["decision"]["rules"]) == 13


def test_unknown_ticker_is_a_404(seeded):
    response = seeded.get(f"{API}/stocks/ZZZZ", headers=KEY)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_bars_endpoint_returns_chart_data(seeded):
    body = seeded.get(f"{API}/stocks/NVDA/bars", headers=KEY, params={"limit": 120}).json()
    assert len(body["bars"]) == 120
    assert set(body["bars"][0]) == {"ts_utc", "o", "h", "l", "c", "v"}
    for overlay in ("ema20", "ema50", "sma200", "rsi14", "macd", "macd_signal", "macd_hist"):
        assert len(body["overlays"][overlay]) == 120


# --------------------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------------------


def test_alert_tabs_all_respond(seeded):
    for path in ("", "/buy", "/sell", "/active", "/closed"):
        response = seeded.get(f"{API}/alerts{path}", headers=KEY)
        assert response.status_code == 200, path
        assert "alerts" in response.json()


def test_there_is_no_endpoint_that_deletes_an_alert(client):
    """Requirement: alerts are permanent. No DELETE route may exist."""
    spec = client.app.openapi()
    for path, methods in spec["paths"].items():
        assert "delete" not in methods, f"{path} exposes DELETE"


def test_positions_history_and_analytics_respond(seeded):
    positions = seeded.get(f"{API}/positions", headers=KEY).json()
    assert positions["portfolio"]["paper_trading"] is True

    assert seeded.get(f"{API}/history", headers=KEY).status_code == 200

    analytics = seeded.get(f"{API}/analytics", headers=KEY).json()
    for field in ("total_buy_signals", "open_alerts", "closed_trades", "win_rate",
                  "profit_factor", "expectancy_r", "max_drawdown_pct", "sharpe", "sortino"):
        assert field in analytics, field

    assert seeded.get(f"{API}/performance/equity-curve", headers=KEY).status_code == 200


# --------------------------------------------------------------------------------------
# Settings and strategy versioning
# --------------------------------------------------------------------------------------


def test_settings_are_grouped_and_self_describing(client):
    body = client.get(f"{API}/settings", headers=KEY).json()
    assert body["paper_trading"] is True
    assert "buy_gate" in body["sections"]
    field = body["sections"]["buy_gate"]["fields"]["min_opportunity_score"]
    assert field["value"] == 80.0
    assert field["default"] == 80.0


def test_operational_settings_can_be_changed_in_place(client):
    response = client.put(
        f"{API}/settings", headers=KEY,
        json={"updates": {"max_open_positions": 8}},
    )
    assert response.status_code == 200
    assert response.json()["sections"]["portfolio"]["fields"]["max_open_positions"]["value"] == 8


def test_changing_judgement_parameters_requires_a_new_version(client):
    """Requirement 48 — historical alerts must stay comparable."""
    blocked = client.put(
        f"{API}/settings", headers=KEY,
        json={"updates": {"min_opportunity_score": 85}},
    )
    assert blocked.status_code == 422
    assert "create_version" in blocked.json()["error"]["message"]

    allowed = client.put(
        f"{API}/settings", headers=KEY,
        json={"updates": {"min_opportunity_score": 85}, "create_version": True},
    )
    assert allowed.status_code == 200
    assert allowed.json()["strategy_version"] != "momentum_breakout_v1.0.0"

    versions = client.get(f"{API}/strategy-versions", headers=KEY).json()["versions"]
    assert len(versions) >= 1


def test_an_unknown_setting_is_rejected(client):
    response = client.put(f"{API}/settings", headers=KEY, json={"updates": {"nope": 1}})
    assert response.status_code == 422


# --------------------------------------------------------------------------------------
# System and sync
# --------------------------------------------------------------------------------------


def test_system_status_reports_provider_and_database_health(seeded):
    body = seeded.get(f"{API}/system/status", headers=KEY).json()
    assert body["database"]["ok"] is True
    assert body["providers"][0]["name"] == "synthetic"
    assert body["instruments"] > 0
    assert body["eligible_instruments"] > 0
    assert body["paper_trading"] is True


def test_audit_log_records_every_decision(seeded):
    entries = seeded.get(f"{API}/audit", headers=KEY).json()["entries"]
    assert entries
    decisions = {e["decision"] for e in entries}
    assert decisions & {"BUY", "NO_BUY"}
    for entry in entries:
        if entry["decision"] == "NO_BUY":
            assert entry["rules_failed"], "a rejection must record why"


def test_sync_returns_one_payload_for_the_android_client(seeded):
    body = seeded.get(f"{API}/sync", headers=KEY).json()
    for field in ("server_time_utc", "next_since", "market_status", "regime",
                  "alerts", "sell_alerts", "positions", "portfolio", "scanner", "analytics"):
        assert field in body, field
    assert body["next_since"].endswith("Z")


def test_sync_since_filters_to_changes(seeded):
    first = seeded.get(f"{API}/sync", headers=KEY).json()
    second = seeded.get(f"{API}/sync", headers=KEY, params={"since": first["next_since"]}).json()
    assert len(second["alerts"]) <= len(first["alerts"])


# --------------------------------------------------------------------------------------
# Full pipeline
# --------------------------------------------------------------------------------------


def test_buy_active_sell_closed_lifecycle_end_to_end(seeded):
    """Requirement 60.6–60.18 — the whole reason the system exists.

    Drives a real alert through the pipeline, then asserts it is visible in the API at
    every stage, that the SELL references the BUY, and that the closed trade remains
    permanently retrievable.
    """
    from sqlalchemy import select

    from app.db.models import BuyAlert, Instrument
    from app.db.session import session_scope
    from app.domain.signals.sell_engine import SellDecision
    from app.services import lifecycle

    # A qualifying setup is rare by design, so create one deterministically through the
    # same lifecycle service the scanner uses.
    with session_scope() as session:
        instrument = session.execute(
            select(Instrument).where(Instrument.ticker == "NVDA")
        ).scalar_one()
        alert = BuyAlert(
            instrument_id=instrument.id, ticker="NVDA", company_name=instrument.company_name,
            strategy_version="momentum_breakout_v1.0.0", data_provider="synthetic",
            buy_price=100.0, stop_price=95.0, target1_price=107.5, target2_price=115.0,
            initial_risk_per_share=5.0, opportunity_score=91.0, confidence=78.0,
            probability=0.51, probability_sample_size=214, expected_value=0.66,
            reward_risk=2.25, market_regime="BULL", sector="Technology",
            buy_reasons=["Strong bullish trend", "Breakout confirmed on volume"],
            risk_factors=["Earnings in 24 days"],
            status="BUY_SIGNAL", current_price=100.0,
            highest_price_since_buy=100.0, lowest_price_since_buy=100.0,
            current_stop_price=95.0,
        )
        session.add(alert)
        session.flush()
        lifecycle.add_event(session, alert, "BUY_SIGNAL", "BUY SIGNAL", price=100.0)
        alert_uid = alert.alert_uid

    # --- visible as an open alert -------------------------------------------------------
    active = seeded.get(f"{API}/alerts/active", headers=KEY).json()
    assert any(a["alert_uid"] == alert_uid for a in active["alerts"])

    detail = seeded.get(f"{API}/alerts/{alert_uid}", headers=KEY).json()
    assert detail["buy_reasons"], "requirement 60.14 — the app must show why"
    assert detail["stop_price"] == 95.0
    assert detail["target1_price"] == 107.5
    assert detail["is_open"] is True

    # --- tracked while it runs -----------------------------------------------------------
    with session_scope() as session:
        alert = lifecycle.get_alert(session, alert_uid)
        lifecycle.promote_to_active(session, alert)
        lifecycle.apply_price_update(session, alert, price=108.0, bar_high=109.0, bar_low=99.0)

    tracked = seeded.get(f"{API}/alerts/{alert_uid}", headers=KEY).json()
    assert tracked["status"] == "ACTIVE"
    assert tracked["current_return_pct"] == pytest.approx(8.0, abs=0.01)
    assert tracked["max_gain_pct"] == pytest.approx(9.0, abs=0.01)
    assert tracked["max_drawdown_pct"] == pytest.approx(-1.0, abs=0.01)

    # --- closed by a SELL ----------------------------------------------------------------
    with session_scope() as session:
        alert = lifecycle.get_alert(session, alert_uid)
        lifecycle.record_sell(
            session, alert,
            SellDecision(
                should_sell=True, exit_reason="TRAILING_STOP",
                detail="Trailing stop triggered", fraction=1.0, suggested_fill=107.8,
                rules_fired=["trailing_stop"], trailing=None, new_status="SELL_SIGNAL",
            ),
            price=107.8, regime="BULL",
        )

    closed = seeded.get(f"{API}/alerts/{alert_uid}", headers=KEY).json()
    assert closed["status"] == "CLOSED"
    assert closed["final_return_pct"] == pytest.approx(7.8, abs=0.01)
    assert closed["sell"]["exit_reason"] == "TRAILING_STOP"

    # --- the SELL references its BUY (requirement 60.17) ----------------------------------
    sells = seeded.get(f"{API}/alerts/sell", headers=KEY).json()["alerts"]
    match = next(s for s in sells if s["buy_alert"]["alert_uid"] == alert_uid)
    assert match["buy_alert_id"] == closed["id"]
    assert match["entry_price"] == pytest.approx(100.0)

    # --- the timeline is complete and permanent (requirement 60.22) -----------------------
    timeline = seeded.get(f"{API}/alerts/{alert_uid}/timeline", headers=KEY).json()
    types = [e["event_type"] for e in timeline["events"]]
    assert types[0] == "BUY_SIGNAL"
    assert "SELL_SIGNAL" in types
    assert types[-1] == "CLOSED"

    # --- and it is still in history (requirement 60.18) ------------------------------------
    history = seeded.get(f"{API}/history", headers=KEY).json()
    assert any(t["alert_uid"] == alert_uid for t in history["trades"])

    closed_tab = seeded.get(f"{API}/alerts/closed", headers=KEY).json()
    assert any(a["alert_uid"] == alert_uid for a in closed_tab["alerts"])


# --------------------------------------------------------------------------------------
# Prohibited integrations
# --------------------------------------------------------------------------------------

FORBIDDEN = (
    "telegram", "discord", "slack", "whatsapp", "twilio", "sendgrid", "mailgun",
    "smtplib", "nodemailer", "sns.publish", "smtp",
)


def test_no_external_notification_integration_exists_anywhere():
    """Requirement 56, enforced rather than asserted in prose.

    Greps the entire repository source. The Alert Center plus local Android notifications
    are the only delivery mechanisms; nothing may reach outside the system.
    """
    repo_root = Path(__file__).resolve().parents[2]
    hits: list[str] = []

    for path in repo_root.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".kt", ".kts", ".xml", ".toml", ".yml", ".yaml"}:
            continue
        if any(part in {".git", ".venv", "build", "node_modules", ".gradle"} for part in path.parts):
            continue
        # The two guards themselves must name the banned services in order to ban them.
        if path.name == "test_api.py" or path.as_posix().endswith(".github/workflows/backend.yml"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        for needle in FORBIDDEN:
            if needle in text:
                hits.append(f"{path.relative_to(repo_root)}: {needle}")

    assert not hits, "prohibited external notification integration found:\n" + "\n".join(hits)


def test_no_api_credentials_are_committed():
    """Requirement 52 — .env must never be committed, and .env.example holds no secrets."""
    repo_root = Path(__file__).resolve().parents[2]
    assert not (repo_root / "backend" / ".env").exists(), ".env must not be committed"

    example = (repo_root / "backend" / ".env.example").read_text()
    for line in example.splitlines():
        if "API_KEY=" in line and not line.strip().startswith("#"):
            _, _, value = line.partition("=")
            assert value.strip() == "", f"a real-looking secret is present: {line}"
