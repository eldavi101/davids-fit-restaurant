"""REST adapters for the supported market-data vendors.

Five vendors, one interface. Each adapter's job is narrow: call the vendor, translate its
payload into the domain types, and normalise its failure modes. Nothing above this module
knows a vendor's field names, and no strategy logic lives here.

Credentials come from the backend environment only. They are never sent to the Android
client and never embedded in the APK (requirement 52).

Adapters return empty results rather than raising for missing symbols; genuine transport
or auth failures raise ``ProviderError`` so the registry can fail over and the scanner can
record a data-integrity refusal instead of inventing a signal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.data.providers.base import MarketDataProvider, ProviderHealth
from app.domain.types import Bar, Fundamentals, InstrumentInfo, Quote

log = get_logger(__name__)

_EXCHANGE_MAP = {
    "XNAS": "NASDAQ", "NASDAQ": "NASDAQ", "NMS": "NASDAQ", "NASDAQ NMS - GLOBAL MARKET": "NASDAQ",
    "XNYS": "NYSE", "NYSE": "NYSE", "NYQ": "NYSE", "NEW YORK STOCK EXCHANGE, INC.": "NYSE",
    "XASE": "NYSE_AMERICAN", "AMEX": "NYSE_AMERICAN", "ASE": "NYSE_AMERICAN",
    "NYSE AMERICAN": "NYSE_AMERICAN", "NYSE MKT": "NYSE_AMERICAN",
}

_LEVERAGED_HINTS = ("2X", "3X", "ULTRA", "LEVERAGED")
_INVERSE_HINTS = ("INVERSE", "SHORT", "BEAR", "-1X")


def normalize_exchange(raw: str | None) -> str | None:
    if not raw:
        return None
    return _EXCHANGE_MAP.get(raw.strip().upper(), raw.strip().upper())


def classify_etf_flags(name: str | None) -> tuple[bool, bool]:
    """(leveraged, inverse) inferred from the fund name.

    Name-based inference is imperfect, which is precisely why leveraged and inverse funds
    are excluded by default rather than merely down-weighted.
    """
    upper = (name or "").upper()
    return (
        any(h in upper for h in _LEVERAGED_HINTS),
        any(h in upper for h in _INVERSE_HINTS),
    )


def _epoch_ms_to_utc(ms: float) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC)


class _RestProvider(MarketDataProvider):
    """Shared HTTP plumbing: timeouts, retries, auth, error translation."""

    base_url: str = ""

    def __init__(self, api_key: str | None, timeout: float = 20.0):
        if not api_key:
            raise ProviderError(f"{self.name} requires an API key; set it in the backend environment")
        self.api_key = api_key
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"User-Agent": "equity-signal-tracker/1.0"},
        )

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        try:
            response = self._client.get(path, params=params or {})
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} transport error: {exc}") from exc
        if response.status_code in (401, 403):
            raise ProviderError(f"{self.name} rejected the API key ({response.status_code})")
        if response.status_code == 429:
            raise ProviderError(f"{self.name} rate limit exceeded")
        if response.status_code >= 400:
            raise ProviderError(f"{self.name} HTTP {response.status_code}: {response.text[:200]}")
        return response.json()

    def close(self) -> None:
        self._client.close()

    def health(self) -> ProviderHealth:
        from app.core.clock import utc_now

        try:
            self.get_quote("SPY")
            return ProviderHealth(self.name, True, "reachable", utc_now())
        except ProviderError as exc:
            return ProviderHealth(self.name, False, str(exc), utc_now())


# --------------------------------------------------------------------------------------
# Polygon.io
# --------------------------------------------------------------------------------------


class PolygonProvider(_RestProvider):
    name = "polygon"
    base_url = "https://api.polygon.io"
    supports_delisted = True  # /v3/reference/tickers supports active=false

    def list_universe(self) -> list[InstrumentInfo]:
        out: list[InstrumentInfo] = []
        cursor: str | None = None
        for _ in range(20):  # bounded pagination
            params = {
                "market": "stocks", "active": "true", "limit": 1000, "apiKey": self.api_key,
            }
            if cursor:
                params["cursor"] = cursor
            payload = self._get("/v3/reference/tickers", params)
            results = payload.get("results", []) if isinstance(payload, dict) else []
            for row in results:
                asset_type = (row.get("type") or "").upper()
                name = row.get("name")
                leveraged, inverse = classify_etf_flags(name)
                out.append(
                    InstrumentInfo(
                        ticker=row.get("ticker", ""),
                        company_name=name,
                        exchange=normalize_exchange(row.get("primary_exchange")),
                        security_type=(
                            "ETF" if asset_type in ("ETF", "ETN", "FUND")
                            else "ADR" if asset_type.startswith("ADR")
                            else "COMMON"
                        ),
                        is_etf=asset_type in ("ETF", "ETN", "FUND"),
                        is_adr=asset_type.startswith("ADR"),
                        is_leveraged_etf=leveraged,
                        is_inverse_etf=inverse,
                        is_otc=(row.get("primary_exchange") or "").upper().startswith("OTC"),
                    )
                )
            cursor = None
            next_url = payload.get("next_url") if isinstance(payload, dict) else None
            if not next_url:
                break
            cursor = next_url.split("cursor=")[-1]
        return [i for i in out if i.ticker]

    def get_bars(self, ticker, timeframe="1d", limit=400, start=None, end=None) -> list[Bar]:
        span = {"1d": ("1", "day"), "1h": ("1", "hour"), "5m": ("5", "minute")}.get(
            timeframe, ("1", "day")
        )
        end_dt = end or datetime.now(UTC)
        start_dt = start or end_dt - timedelta(days=int(limit * 1.6) + 10)
        payload = self._get(
            f"/v2/aggs/ticker/{ticker}/range/{span[0]}/{span[1]}/"
            f"{start_dt:%Y-%m-%d}/{end_dt:%Y-%m-%d}",
            {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": self.api_key},
        )
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        bars = [
            Bar(
                ts=_epoch_ms_to_utc(r["t"]),
                open=float(r["o"]), high=float(r["h"]), low=float(r["l"]),
                close=float(r["c"]), volume=float(r.get("v", 0.0)),
            )
            for r in rows
        ]
        return bars[-limit:]

    def get_quote(self, ticker: str) -> Quote | None:
        payload = self._get(f"/v2/last/nbbo/{ticker}", {"apiKey": self.api_key})
        row = payload.get("results") if isinstance(payload, dict) else None
        if not row:
            return None
        bid, ask = float(row.get("p", 0) or 0), float(row.get("P", 0) or 0)
        mid = (bid + ask) / 2 if bid and ask else (bid or ask)
        return Quote(ticker, last=mid, bid=bid or None, ask=ask or None,
                     ts=_epoch_ms_to_utc(row["t"] / 1e6) if row.get("t") else None)


# --------------------------------------------------------------------------------------
# Finnhub
# --------------------------------------------------------------------------------------


class FinnhubProvider(_RestProvider):
    name = "finnhub"
    base_url = "https://finnhub.io/api/v1"

    def list_universe(self) -> list[InstrumentInfo]:
        rows = self._get("/stock/symbol", {"exchange": "US", "token": self.api_key})
        out: list[InstrumentInfo] = []
        for row in rows if isinstance(rows, list) else []:
            asset_type = (row.get("type") or "").upper()
            name = row.get("description")
            leveraged, inverse = classify_etf_flags(name)
            out.append(
                InstrumentInfo(
                    ticker=row.get("symbol", ""),
                    company_name=name,
                    exchange=normalize_exchange(row.get("mic")),
                    security_type="ETF" if "ETF" in asset_type else "COMMON",
                    is_etf="ETF" in asset_type,
                    is_adr="ADR" in asset_type,
                    is_leveraged_etf=leveraged,
                    is_inverse_etf=inverse,
                )
            )
        return [i for i in out if i.ticker]

    def get_bars(self, ticker, timeframe="1d", limit=400, start=None, end=None) -> list[Bar]:
        resolution = {"1d": "D", "1h": "60", "5m": "5"}.get(timeframe, "D")
        end_dt = end or datetime.now(UTC)
        start_dt = start or end_dt - timedelta(days=int(limit * 1.6) + 10)
        payload = self._get(
            "/stock/candle",
            {
                "symbol": ticker, "resolution": resolution,
                "from": int(start_dt.timestamp()), "to": int(end_dt.timestamp()),
                "token": self.api_key,
            },
        )
        if not isinstance(payload, dict) or payload.get("s") != "ok":
            return []
        bars = [
            Bar(
                ts=datetime.fromtimestamp(t, tz=UTC),
                open=float(o), high=float(h), low=float(low_), close=float(c), volume=float(v),
            )
            for t, o, h, low_, c, v in zip(
                payload["t"], payload["o"], payload["h"], payload["l"],
                payload["c"], payload["v"], strict=False,
            )
        ]
        return bars[-limit:]

    def get_quote(self, ticker: str) -> Quote | None:
        payload = self._get("/quote", {"symbol": ticker, "token": self.api_key})
        if not isinstance(payload, dict) or not payload.get("c"):
            return None
        return Quote(ticker, last=float(payload["c"]), ts=datetime.now(UTC))

    def get_fundamentals(self, ticker: str) -> Fundamentals | None:
        payload = self._get("/stock/metric", {"symbol": ticker, "metric": "all", "token": self.api_key})
        metric = payload.get("metric", {}) if isinstance(payload, dict) else {}
        if not metric:
            return None

        def pct(key: str) -> float | None:
            value = metric.get(key)
            return None if value is None else float(value) / 100.0

        return Fundamentals(
            ticker=ticker,
            revenue_growth_yoy=pct("revenueGrowthTTMYoy"),
            earnings_growth_yoy=pct("epsGrowthTTMYoy"),
            operating_margin=pct("operatingMarginTTM"),
            net_margin=pct("netProfitMarginTTM"),
            roe=pct("roeTTM"),
            debt_to_equity=metric.get("totalDebt/totalEquityQuarterly"),
            pe=metric.get("peTTM"),
            peg=metric.get("pegTTM"),
        )


# --------------------------------------------------------------------------------------
# Financial Modeling Prep
# --------------------------------------------------------------------------------------


class FmpProvider(_RestProvider):
    name = "fmp"
    base_url = "https://financialmodelingprep.com/api/v3"

    def list_universe(self) -> list[InstrumentInfo]:
        rows = self._get("/stock/list", {"apikey": self.api_key})
        out: list[InstrumentInfo] = []
        for row in rows if isinstance(rows, list) else []:
            asset_type = (row.get("type") or "").lower()
            name = row.get("name")
            leveraged, inverse = classify_etf_flags(name)
            exchange = normalize_exchange(row.get("exchangeShortName"))
            out.append(
                InstrumentInfo(
                    ticker=row.get("symbol", ""),
                    company_name=name,
                    exchange=exchange,
                    security_type="ETF" if asset_type == "etf" else "COMMON",
                    is_etf=asset_type == "etf",
                    is_leveraged_etf=leveraged,
                    is_inverse_etf=inverse,
                    is_otc=(exchange or "").startswith("OTC"),
                )
            )
        return [i for i in out if i.ticker]

    def get_bars(self, ticker, timeframe="1d", limit=400, start=None, end=None) -> list[Bar]:
        payload = self._get(
            f"/historical-price-full/{ticker}",
            {"timeseries": min(limit, 5000), "apikey": self.api_key},
        )
        rows = payload.get("historical", []) if isinstance(payload, dict) else []
        bars = [
            Bar(
                ts=datetime.strptime(r["date"], "%Y-%m-%d").replace(tzinfo=UTC),
                open=float(r["open"]), high=float(r["high"]), low=float(r["low"]),
                # FMP's adjClose is the split/dividend-adjusted series we score on.
                close=float(r.get("adjClose", r["close"])),
                volume=float(r.get("volume", 0.0)),
                raw_close=float(r["close"]),
            )
            for r in rows
        ]
        bars.sort(key=lambda b: b.ts)
        return bars[-limit:]

    def get_quote(self, ticker: str) -> Quote | None:
        rows = self._get(f"/quote/{ticker}", {"apikey": self.api_key})
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0]
        return Quote(
            ticker, last=float(row.get("price", 0.0)),
            bid=row.get("bid"), ask=row.get("ask"), ts=datetime.now(UTC),
        )

    def get_fundamentals(self, ticker: str) -> Fundamentals | None:
        rows = self._get(f"/key-metrics-ttm/{ticker}", {"apikey": self.api_key})
        if not isinstance(rows, list) or not rows:
            return None
        m = rows[0]
        return Fundamentals(
            ticker=ticker,
            free_cash_flow=m.get("freeCashFlowPerShareTTM"),
            debt_to_equity=m.get("debtToEquityTTM"),
            roe=m.get("roeTTM"),
            pe=m.get("peRatioTTM"),
            peg=m.get("pegRatioTTM"),
        )


# --------------------------------------------------------------------------------------
# Twelve Data
# --------------------------------------------------------------------------------------


class TwelveDataProvider(_RestProvider):
    name = "twelvedata"
    base_url = "https://api.twelvedata.com"

    def list_universe(self) -> list[InstrumentInfo]:
        payload = self._get("/stocks", {"country": "United States", "apikey": self.api_key})
        rows = payload.get("data", []) if isinstance(payload, dict) else []
        return [
            InstrumentInfo(
                ticker=r.get("symbol", ""),
                company_name=r.get("name"),
                exchange=normalize_exchange(r.get("exchange")),
                security_type="COMMON",
            )
            for r in rows
            if r.get("symbol")
        ]

    def get_bars(self, ticker, timeframe="1d", limit=400, start=None, end=None) -> list[Bar]:
        interval = {"1d": "1day", "1h": "1h", "5m": "5min"}.get(timeframe, "1day")
        payload = self._get(
            "/time_series",
            {
                "symbol": ticker, "interval": interval, "outputsize": min(limit, 5000),
                "apikey": self.api_key, "order": "ASC",
            },
        )
        rows = payload.get("values", []) if isinstance(payload, dict) else []
        bars: list[Bar] = []
        for r in rows:
            raw_ts = r.get("datetime", "")
            fmt = "%Y-%m-%d %H:%M:%S" if " " in raw_ts else "%Y-%m-%d"
            bars.append(
                Bar(
                    ts=datetime.strptime(raw_ts, fmt).replace(tzinfo=UTC),
                    open=float(r["open"]), high=float(r["high"]), low=float(r["low"]),
                    close=float(r["close"]), volume=float(r.get("volume", 0) or 0),
                )
            )
        return bars[-limit:]

    def get_quote(self, ticker: str) -> Quote | None:
        payload = self._get("/quote", {"symbol": ticker, "apikey": self.api_key})
        if not isinstance(payload, dict) or "close" not in payload:
            return None
        return Quote(ticker, last=float(payload["close"]), ts=datetime.now(UTC))


# --------------------------------------------------------------------------------------
# Alpha Vantage
# --------------------------------------------------------------------------------------


class AlphaVantageProvider(_RestProvider):
    name = "alphavantage"
    base_url = "https://www.alphavantage.co"

    def list_universe(self) -> list[InstrumentInfo]:
        # Alpha Vantage's listing endpoint returns CSV; the adapter deliberately does not
        # act as a universe source. Use it for bars/fundamentals alongside another vendor.
        return []

    def get_bars(self, ticker, timeframe="1d", limit=400, start=None, end=None) -> list[Bar]:
        payload = self._get(
            "/query",
            {
                "function": "TIME_SERIES_DAILY_ADJUSTED", "symbol": ticker,
                "outputsize": "full" if limit > 100 else "compact", "apikey": self.api_key,
            },
        )
        series = payload.get("Time Series (Daily)", {}) if isinstance(payload, dict) else {}
        bars = [
            Bar(
                ts=datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC),
                open=float(v["1. open"]), high=float(v["2. high"]), low=float(v["3. low"]),
                close=float(v["5. adjusted close"]), volume=float(v["6. volume"]),
                raw_close=float(v["4. close"]),
                split_factor=float(v.get("8. split coefficient", 1.0)),
                dividend=float(v.get("7. dividend amount", 0.0)),
            )
            for day, v in series.items()
        ]
        bars.sort(key=lambda b: b.ts)
        return bars[-limit:]

    def get_quote(self, ticker: str) -> Quote | None:
        payload = self._get("/query", {"function": "GLOBAL_QUOTE", "symbol": ticker, "apikey": self.api_key})
        row = payload.get("Global Quote", {}) if isinstance(payload, dict) else {}
        price = row.get("05. price")
        if not price:
            return None
        return Quote(ticker, last=float(price), ts=datetime.now(UTC))
