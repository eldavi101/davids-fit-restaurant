"""Time handling.

Rule for the whole system (requirement 61.18): **UTC internally, America/New_York for
market semantics and display**. Conversion happens at the presentation boundary only.

Every function here returns timezone-aware datetimes. A naive datetime entering the
system is a bug, and ``ensure_utc`` raises on one rather than guessing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("America/New_York")

REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
PRE_OPEN = time(4, 0)
POST_CLOSE = time(20, 0)


class MarketSession(str, Enum):
    PRE = "PRE"
    OPEN = "OPEN"
    POST = "POST"
    CLOSED = "CLOSED"
    HOLIDAY = "HOLIDAY"


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime rejected; all timestamps must be timezone-aware")
    return dt.astimezone(UTC)


def to_market_time(dt: datetime) -> datetime:
    return ensure_utc(dt).astimezone(MARKET_TZ)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return ensure_utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------------------
# Holidays
# --------------------------------------------------------------------------------------
# Fixed and observed U.S. equity market holidays. Rule-derived rather than a hard-coded
# table so it does not silently expire; Good Friday is computed from Easter.


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month, 28)
    while d.month == month:
        nxt = d + timedelta(days=1)
        if nxt.month != month:
            break
        d = nxt
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _easter(year: int) -> date:
    """Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def _observed(d: date) -> date:
    if d.weekday() == 5:  # Saturday -> Friday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday -> Monday
        return d + timedelta(days=1)
    return d


def market_holidays(year: int) -> set[date]:
    return {
        _observed(date(year, 1, 1)),                      # New Year's Day
        _nth_weekday(year, 1, 0, 3),                      # MLK Day
        _nth_weekday(year, 2, 0, 3),                      # Presidents' Day
        _easter(year) - timedelta(days=2),                # Good Friday
        _last_weekday(year, 5, 0),                        # Memorial Day
        _observed(date(year, 6, 19)),                     # Juneteenth
        _observed(date(year, 7, 4)),                      # Independence Day
        _nth_weekday(year, 9, 0, 1),                      # Labor Day
        _nth_weekday(year, 11, 3, 4),                     # Thanksgiving
        _observed(date(year, 12, 25)),                    # Christmas
    }


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in market_holidays(d.year)


def market_session(now: datetime | None = None) -> MarketSession:
    et = to_market_time(now or utc_now())
    if not is_trading_day(et.date()):
        return MarketSession.HOLIDAY if et.weekday() < 5 else MarketSession.CLOSED
    t = et.time()
    if REGULAR_OPEN <= t < REGULAR_CLOSE:
        return MarketSession.OPEN
    if PRE_OPEN <= t < REGULAR_OPEN:
        return MarketSession.PRE
    if REGULAR_CLOSE <= t < POST_CLOSE:
        return MarketSession.POST
    return MarketSession.CLOSED


def is_market_open(now: datetime | None = None) -> bool:
    return market_session(now) is MarketSession.OPEN


def _session_bound(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=MARKET_TZ).astimezone(UTC)


def next_market_open(now: datetime | None = None) -> datetime:
    et = to_market_time(now or utc_now())
    d = et.date()
    if is_trading_day(d) and et.time() < REGULAR_OPEN:
        return _session_bound(d, REGULAR_OPEN)
    d += timedelta(days=1)
    for _ in range(15):
        if is_trading_day(d):
            return _session_bound(d, REGULAR_OPEN)
        d += timedelta(days=1)
    raise RuntimeError("no trading day found within 15 days")


def next_market_close(now: datetime | None = None) -> datetime:
    et = to_market_time(now or utc_now())
    d = et.date()
    if is_trading_day(d) and et.time() < REGULAR_CLOSE:
        return _session_bound(d, REGULAR_CLOSE)
    d += timedelta(days=1)
    for _ in range(15):
        if is_trading_day(d):
            return _session_bound(d, REGULAR_CLOSE)
        d += timedelta(days=1)
    raise RuntimeError("no trading day found within 15 days")


def trading_days_between(start: date, end: date) -> int:
    """Inclusive of start, exclusive of end."""
    if end <= start:
        return 0
    days, d = 0, start
    while d < end:
        if is_trading_day(d):
            days += 1
        d += timedelta(days=1)
    return days
