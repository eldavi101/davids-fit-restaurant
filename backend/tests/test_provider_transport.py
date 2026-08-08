"""Pacing, retries and universe pre-screening — the parts that decide whether a real
vendor key survives a full scan.

These are the failure modes that only appear against a live, metered API: bursts that
blow a per-minute budget, transient 429/5xx answers, and spending a request on a symbol
that was never eligible. All three are exercised here without touching the network.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import UniverseConfig
from app.core.errors import ProviderError
from app.data.providers.rest import _RestProvider
from app.data.providers.throttle import RateLimiter
from app.data.universe import LiquidityFacts, check_eligibility, prescreen
from app.domain.types import InstrumentInfo


class FakeClock:
    """Monotonic time that only advances when something sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


# --------------------------------------------------------------------------------------
# rate limiter
# --------------------------------------------------------------------------------------


def test_limiter_allows_the_budget_then_waits_for_the_window():
    clock = FakeClock()
    limiter = RateLimiter(5, monotonic=clock.monotonic, sleep=clock.sleep)

    for _ in range(5):
        assert limiter.acquire() == 0.0
    assert clock.slept == []

    # The sixth call in the same minute must wait for the first one to age out.
    waited = limiter.acquire()
    assert waited == pytest.approx(60.0)
    assert clock.now == pytest.approx(60.0)


def test_limiter_is_a_noop_when_disabled():
    clock = FakeClock()
    limiter = RateLimiter(0, monotonic=clock.monotonic, sleep=clock.sleep)
    for _ in range(1000):
        assert limiter.acquire() == 0.0
    assert clock.slept == []


def test_limiter_window_slides_rather_than_resetting():
    clock = FakeClock()
    limiter = RateLimiter(2, monotonic=clock.monotonic, sleep=clock.sleep)
    limiter.acquire()
    clock.now = 30.0
    limiter.acquire()

    # First hit expires at t=60, so the wait is 30s — not a full fresh minute.
    assert limiter.acquire() == pytest.approx(30.0)


# --------------------------------------------------------------------------------------
# retry behaviour
# --------------------------------------------------------------------------------------


class StubProvider(_RestProvider):
    """A ``_RestProvider`` whose transport is a scripted list of responses."""

    name = "stub"
    base_url = "https://stub.invalid"

    def __init__(self, responses):
        super().__init__(api_key="k", retry_backoff_base=1.0, limiter=RateLimiter(0))
        self._responses = list(responses)
        self.calls = 0
        self.slept: list[float] = []
        self._client = self  # type: ignore[assignment]

    # stands in for httpx.Client.get
    def get(self, path, params=None):
        self.calls += 1
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def _sleep(self, seconds: float) -> None:
        self.slept.append(seconds)

    def list_universe(self):  # pragma: no cover - unused
        return []

    def get_bars(self, ticker, timeframe="1d", limit=400, start=None, end=None):  # pragma: no cover
        return []

    def get_quote(self, ticker):  # pragma: no cover - unused
        return None


def response(status: int, json_body=None, headers=None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=json_body if json_body is not None else {},
        headers=headers or {},
        request=httpx.Request("GET", "https://stub.invalid/x"),
    )


def test_429_is_retried_with_backoff_and_then_succeeds():
    provider = StubProvider([response(429), response(200, {"ok": True})])
    assert provider._get("/x") == {"ok": True}
    assert provider.calls == 2
    assert provider.slept == [1.0]


def test_retry_after_header_overrides_the_backoff():
    provider = StubProvider([response(429, headers={"Retry-After": "7"}), response(200, {"ok": 1})])
    provider._get("/x")
    assert provider.slept == [7.0]


def test_server_errors_are_retried_and_give_up_after_max_attempts():
    provider = StubProvider([response(503), response(503), response(503)])
    with pytest.raises(ProviderError):
        provider._get("/x")
    assert provider.calls == provider.max_attempts
    assert provider.slept == [1.0, 2.0]  # exponential


def test_a_rejected_api_key_is_never_retried():
    # Retrying an auth failure only burns quota and hides the message the operator needs.
    provider = StubProvider([response(401), response(200, {"ok": 1})])
    with pytest.raises(ProviderError, match="rejected the API key"):
        provider._get("/x")
    assert provider.calls == 1


def test_transport_errors_are_retried():
    provider = StubProvider(
        [httpx.ConnectError("boom"), response(200, {"ok": 1})]
    )
    assert provider._get("/x") == {"ok": 1}
    assert provider.calls == 2


def test_every_request_passes_through_the_limiter():
    clock = FakeClock()
    provider = StubProvider([response(200, {"a": 1}), response(200, {"b": 2})])
    provider.limiter = RateLimiter(1, monotonic=clock.monotonic, sleep=clock.sleep)

    provider._get("/x")
    provider._get("/y")
    assert clock.now == pytest.approx(60.0)


# --------------------------------------------------------------------------------------
# universe pre-screen
# --------------------------------------------------------------------------------------


def info(**kwargs) -> InstrumentInfo:
    base = dict(ticker="AAA", company_name="A", exchange="NASDAQ", security_type="COMMON")
    base.update(kwargs)
    return InstrumentInfo(**base)


def test_prescreen_rejects_what_it_can_decide_without_market_data():
    cfg = UniverseConfig()
    assert prescreen(info(is_otc=True), cfg) is not None
    assert prescreen(info(is_etf=True), cfg) is not None
    assert prescreen(info(exchange="OTHER"), cfg) is not None
    assert prescreen(info(exchange=None), cfg) is not None


def test_prescreen_passes_a_symbol_that_still_needs_its_liquidity_checked():
    assert prescreen(info(), UniverseConfig()) is None


def test_prescreen_and_check_eligibility_agree_on_structural_rejections():
    """The pre-screen is an optimisation, so it must never change an outcome."""
    cfg = UniverseConfig()
    candidates = [
        info(is_otc=True),
        info(is_leveraged_etf=True),
        info(is_inverse_etf=True),
        info(is_etf=True),
        info(is_adr=True),
        info(exchange="LSE"),
    ]
    facts = LiquidityFacts(
        price=100.0, market_cap=5e9, avg_volume_50d=5e6, avg_dollar_volume_50d=5e8
    )
    for candidate in candidates:
        pre = prescreen(candidate, cfg)
        full = check_eligibility(candidate, facts, cfg)
        assert pre is not None
        assert full.eligible is False
        assert pre.reason == full.reason
