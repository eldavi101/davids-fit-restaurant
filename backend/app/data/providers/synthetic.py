"""Deterministic synthetic market-data provider.

**This provider does not produce real market data and never claims to.** Every bar it
emits is generated from a seeded random walk. Its purposes are:

* running the full pipeline in tests and CI without vendor credentials,
* letting the Android app be exercised end-to-end before keys are configured,
* giving the backtester a reproducible fixture.

Requirement 61.1 forbids fabricating market data, so this provider is quarantined behind
three guards: it is only selectable by explicitly setting ``MARKET_DATA_PROVIDER=synthetic``,
every instrument it returns carries ``data_provider="synthetic"`` all the way into the
database and the API, and ``GET /market/status`` reports ``"synthetic_data": true`` so the
app can label the screen. Nothing here is ever presented as a real quote.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

import numpy as np

from app.core.clock import is_trading_day, utc_now
from app.data.providers.base import MarketDataProvider, ProviderHealth
from app.domain.types import Bar, Fundamentals, InstrumentInfo, Quote

# A small, sector-diverse set of large-cap U.S. names plus the ETFs the regime engine
# needs. Real tickers, entirely synthetic prices.
_UNIVERSE: tuple[tuple[str, str, str, str, str, float], ...] = (
    ("NVDA", "NVIDIA Corp", "NASDAQ", "Technology", "Semiconductors", 4.2e12),
    ("AMD", "Advanced Micro Devices", "NASDAQ", "Technology", "Semiconductors", 3.1e11),
    ("MSFT", "Microsoft Corp", "NASDAQ", "Technology", "Software", 3.4e12),
    ("AAPL", "Apple Inc", "NASDAQ", "Technology", "Consumer Electronics", 3.3e12),
    ("META", "Meta Platforms", "NASDAQ", "Communication Services", "Interactive Media", 1.5e12),
    ("GOOGL", "Alphabet Inc", "NASDAQ", "Communication Services", "Interactive Media", 2.3e12),
    ("AMZN", "Amazon.com Inc", "NASDAQ", "Consumer Discretionary", "Internet Retail", 2.1e12),
    ("TSLA", "Tesla Inc", "NASDAQ", "Consumer Discretionary", "Auto Manufacturers", 8.9e11),
    ("JPM", "JPMorgan Chase", "NYSE", "Financials", "Banks", 6.8e11),
    ("V", "Visa Inc", "NYSE", "Financials", "Credit Services", 5.9e11),
    ("UNH", "UnitedHealth Group", "NYSE", "Health Care", "Healthcare Plans", 4.6e11),
    ("LLY", "Eli Lilly", "NYSE", "Health Care", "Drug Manufacturers", 7.2e11),
    ("XOM", "Exxon Mobil", "NYSE", "Energy", "Oil & Gas", 4.8e11),
    ("CAT", "Caterpillar Inc", "NYSE", "Industrials", "Farm & Heavy Machinery", 1.8e11),
    ("COST", "Costco Wholesale", "NASDAQ", "Consumer Staples", "Discount Stores", 4.1e11),
    ("NEE", "NextEra Energy", "NYSE", "Utilities", "Utilities - Regulated", 1.5e11),
    ("LIN", "Linde plc", "NASDAQ", "Materials", "Specialty Chemicals", 2.1e11),
    ("PLD", "Prologis Inc", "NYSE", "Real Estate", "REIT - Industrial", 1.1e11),
    ("PANW", "Palo Alto Networks", "NASDAQ", "Technology", "Software - Infrastructure", 1.2e11),
    ("SMCI", "Super Micro Computer", "NASDAQ", "Technology", "Computer Hardware", 2.4e10),
)

_ETFS: tuple[tuple[str, str], ...] = (
    ("SPY", "SPDR S&P 500 ETF Trust"),
    ("QQQ", "Invesco QQQ Trust"),
    ("IWM", "iShares Russell 2000 ETF"),
    ("XLK", "Technology Select Sector SPDR"),
    ("XLF", "Financial Select Sector SPDR"),
    ("XLV", "Health Care Select Sector SPDR"),
    ("XLE", "Energy Select Sector SPDR"),
    ("XLI", "Industrial Select Sector SPDR"),
    ("XLY", "Consumer Discretionary Select Sector SPDR"),
    ("XLP", "Consumer Staples Select Sector SPDR"),
    ("XLU", "Utilities Select Sector SPDR"),
    ("XLB", "Materials Select Sector SPDR"),
    ("XLRE", "Real Estate Select Sector SPDR"),
    ("XLC", "Communication Services Select Sector SPDR"),
)

SECTOR_ETF = {
    "Technology": "XLK",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


def _seed(ticker: str) -> int:
    return int(hashlib.sha256(ticker.encode()).hexdigest()[:8], 16)


class SyntheticProvider(MarketDataProvider):
    name = "synthetic"
    supports_delisted = False

    def __init__(self, drift: float = 0.0004, volatility: float = 0.018, bars: int = 800):
        self.drift = drift
        self.volatility = volatility
        self.default_bars = bars

    # -- universe -----------------------------------------------------------------------

    def list_universe(self) -> list[InstrumentInfo]:
        out = [
            InstrumentInfo(
                ticker=t,
                company_name=name,
                exchange=exchange,
                security_type="COMMON",
                sector=sector,
                industry=industry,
                market_cap=cap,
            )
            for t, name, exchange, sector, industry, cap in _UNIVERSE
        ]
        out += [
            InstrumentInfo(
                ticker=t,
                company_name=name,
                exchange="NYSE_AMERICAN" if t.startswith("XL") else "NYSE",
                security_type="ETF",
                sector="Index",
                industry="Exchange Traded Fund",
                market_cap=5e10,
                is_etf=True,
            )
            for t, name in _ETFS
        ]
        return out

    # -- bars ----------------------------------------------------------------------------

    def get_bars(self, ticker, timeframe="1d", limit=400, start=None, end=None) -> list[Bar]:
        count = min(max(limit, 1), 2000)
        rng = np.random.default_rng(_seed(ticker))

        base_price = 20.0 + (_seed(ticker) % 400)
        # Benchmarks and sector ETFs move less than single stocks.
        is_etf = ticker in {t for t, _ in _ETFS}
        vol = self.volatility * (0.45 if is_etf else 1.0)
        drift = self.drift * (0.8 if is_etf else 1.0)

        shocks = rng.normal(loc=drift, scale=vol, size=count)
        # A slow cycle keeps trends and pullbacks from being pure noise, which makes the
        # generated series exercise the trend/breakout logic rather than random walk it.
        cycle = 0.0016 * np.sin(np.linspace(0, 6 * np.pi, count))
        closes = base_price * np.exp(np.cumsum(shocks + cycle))

        intraday = np.abs(rng.normal(0.0, vol * 0.6, size=count))
        highs = closes * (1.0 + intraday)
        lows = closes * (1.0 - intraday)
        opens = np.empty(count)
        opens[0] = closes[0]
        opens[1:] = closes[:-1] * (1.0 + rng.normal(0.0, vol * 0.3, size=count - 1))
        opens = np.clip(opens, lows, highs)

        base_volume = 1_500_000 + (_seed(ticker) % 9_000_000)
        volumes = base_volume * np.exp(rng.normal(0.0, 0.35, size=count))

        end_ts = (end or utc_now()).replace(hour=20, minute=0, second=0, microsecond=0)
        dates: list = []
        cursor = end_ts
        while len(dates) < count:
            if is_trading_day(cursor.date()):
                dates.append(cursor)
            cursor -= timedelta(days=1)
        dates.reverse()

        return [
            Bar(
                ts=dates[i],
                open=round(float(opens[i]), 4),
                high=round(float(max(highs[i], opens[i], closes[i])), 4),
                low=round(float(min(lows[i], opens[i], closes[i])), 4),
                close=round(float(closes[i]), 4),
                volume=round(float(volumes[i]), 0),
                raw_close=round(float(closes[i]), 4),
            )
            for i in range(count)
        ]

    # -- quote / fundamentals -------------------------------------------------------------

    def get_quote(self, ticker: str) -> Quote | None:
        bars = self.get_bars(ticker, limit=2)
        if not bars:
            return None
        last = bars[-1].close
        half_spread = max(0.01, last * 0.0002)
        return Quote(
            ticker=ticker,
            last=last,
            bid=round(last - half_spread, 4),
            ask=round(last + half_spread, 4),
            ts=bars[-1].ts,
        )

    def get_fundamentals(self, ticker: str) -> Fundamentals | None:
        if ticker in {t for t, _ in _ETFS}:
            return None
        rng = np.random.default_rng(_seed(ticker) + 7)
        return Fundamentals(
            ticker=ticker,
            revenue_growth_yoy=float(rng.uniform(-0.05, 0.45)),
            earnings_growth_yoy=float(rng.uniform(-0.10, 0.55)),
            eps_surprise_pct=float(rng.uniform(-5.0, 15.0)),
            operating_margin=float(rng.uniform(0.02, 0.42)),
            free_cash_flow=float(rng.uniform(-1e9, 3e10)),
            debt_to_equity=float(rng.uniform(0.1, 2.4)),
            roe=float(rng.uniform(0.02, 0.38)),
            peg=float(rng.uniform(0.6, 4.0)),
            next_earnings_date=utc_now() + timedelta(days=int(rng.integers(3, 80))),
        )

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            name=self.name,
            ok=True,
            detail="synthetic generator — deterministic, NOT real market data",
            checked_at=utc_now(),
        )
