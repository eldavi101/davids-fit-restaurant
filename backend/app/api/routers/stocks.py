"""Per-stock endpoints: profile, full analysis, chart data, signal history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session, require_api_key, strategy_dep
from app.api.serializers import serialize_alert, serialize_instrument, serialize_score
from app.core.clock import iso
from app.core.config import StrategyConfig
from app.core.errors import DataIntegrityError, NotFoundError
from app.data.providers.registry import get_provider
from app.db.models import BuyAlert, Instrument, StockScore
from app.domain.indicators import core as ind
from app.domain.indicators.snapshot import compute_snapshot
from app.domain.probability.model import ProbabilityModel, build_features
from app.domain.regime.engine import classify_regime, neutral_regime
from app.domain.scoring.opportunity import score_stock
from app.domain.signals.buy_engine import BuyContext, evaluate_buy
from app.domain.signals.levels import compute_levels
from app.services.market_data import MarketDataService

router = APIRouter(prefix="/stocks", tags=["stocks"], dependencies=[Depends(require_api_key)])


def _instrument(session: Session, ticker: str) -> Instrument:
    row = session.execute(
        select(Instrument).where(Instrument.ticker == ticker.upper())
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"instrument {ticker} not found")
    return row


@router.get("/{ticker}")
def stock_profile(ticker: str, session: Session = Depends(db_session)) -> dict:
    instrument = _instrument(session, ticker)
    provider = get_provider()
    quote = provider.get_quote(instrument.ticker)
    latest = session.execute(
        select(StockScore)
        .where(StockScore.ticker == instrument.ticker)
        .order_by(StockScore.ts_utc.desc())
        .limit(1)
    ).scalar_one_or_none()
    return {
        **serialize_instrument(instrument),
        "quote": (
            {
                "last": quote.last, "bid": quote.bid, "ask": quote.ask,
                "spread_bps": quote.spread_bps, "ts_utc": iso(quote.ts),
            }
            if quote else None
        ),
        "latest_score": serialize_score(latest) if latest else None,
    }


@router.get("/{ticker}/analysis")
def stock_analysis(
    ticker: str,
    session: Session = Depends(db_session),
    cfg: StrategyConfig = Depends(strategy_dep),
) -> dict:
    """The complete explainability payload (requirement 49).

    Recomputed live so the numbers on screen are the ones the engine would act on right
    now, not a cached approximation.
    """
    instrument = _instrument(session, ticker)
    provider = get_provider()
    service = MarketDataService(provider)

    try:
        series = service.load_series(instrument.ticker)
        benchmarks = service.load_benchmarks()
    except DataIntegrityError as exc:
        return {"ticker": instrument.ticker, "error": str(exc), "analysis_available": False}

    spy = benchmarks.get("SPY")
    try:
        regime = classify_regime(
            benchmark=spy.window(-1) if spy else None,
            sector_windows={s: b.window(-1) for s, b in benchmarks.items() if s.startswith("XL")},
            cfg=cfg,
            secondary={s: benchmarks[s].window(-1) for s in ("QQQ", "IWM") if s in benchmarks},
        )
    except DataIntegrityError:
        regime = neutral_regime(cfg)

    context = service.build_context(benchmarks, instrument.sector, volatility_level=regime.volatility_proxy)
    snapshot = compute_snapshot(series.window(-1), context)
    fundamentals = provider.get_fundamentals(instrument.ticker)
    score = score_stock(snapshot, regime, cfg, fundamentals=fundamentals)
    levels = compute_levels(snapshot, cfg)
    probability = ProbabilityModel(cfg).predict(build_features(score, snapshot, levels, regime))
    quote = provider.get_quote(instrument.ticker)
    health = service.assess_freshness(series, cfg)

    decision = evaluate_buy(
        snapshot, score, levels, probability, regime, cfg,
        BuyContext(
            market_cap=instrument.market_cap,
            spread_bps=quote.spread_bps if quote else None,
            data_fresh=health.fresh,
            data_issues=health.issues,
        ),
    )

    return {
        "ticker": instrument.ticker,
        "company_name": instrument.company_name,
        "analysis_available": True,
        "price": snapshot.close,
        "score": score.breakdown(),
        "levels": levels.as_dict(),
        "probability": probability.as_dict(),
        "regime": regime.as_dict(),
        "indicators": snapshot.as_dict(),
        "fundamentals_available": fundamentals is not None,
        "decision": decision.as_dict(),
        "would_buy": decision.should_buy,
        "buy_reasons": decision.reasons,
        "risk_factors": decision.risk_factors,
        "data_health": {"fresh": health.fresh, "issues": health.issues},
    }


@router.get("/{ticker}/bars")
def stock_bars(
    ticker: str,
    session: Session = Depends(db_session),
    limit: int = Query(300, le=1500),
    timeframe: str = "1d",
) -> dict:
    instrument = _instrument(session, ticker)
    service = MarketDataService(get_provider())
    try:
        series = service.load_series(instrument.ticker, limit=limit + 250, timeframe=timeframe)
    except DataIntegrityError as exc:
        raise NotFoundError(f"no bars available for {ticker}: {exc}") from exc

    close = series.close
    ema20 = ind.ema(close, 20)
    ema50 = ind.ema(close, 50)
    sma200 = ind.sma(close, 200)
    rsi14 = ind.rsi(close, 14)
    macd_line, macd_signal, macd_hist = ind.macd(close)
    obv = ind.obv(close, series.volume)

    take = min(limit, len(series))

    def tail(arr) -> list:
        return [None if v is None or v != v else round(float(v), 4) for v in arr[-take:]]

    alerts = list(
        session.execute(
            select(BuyAlert).where(BuyAlert.ticker == instrument.ticker)
        ).scalars()
    )
    markers = []
    levels: dict = {}
    for alert in alerts:
        markers.append({
            "type": "BUY", "ts_utc": iso(alert.buy_ts_utc),
            "price": round(alert.buy_price, 4), "alert_uid": alert.alert_uid,
        })
        for sell in alert.sells:
            markers.append({
                "type": "SELL", "ts_utc": iso(sell.sell_ts_utc),
                "price": round(sell.sell_price, 4), "alert_uid": alert.alert_uid,
                "exit_reason": sell.exit_reason,
            })
        if alert.is_open:
            levels = {
                "stop": round(alert.current_stop_price or alert.stop_price, 4),
                "target1": round(alert.target1_price, 4),
                "target2": round(alert.target2_price, 4),
                "entry": round(alert.buy_price, 4),
            }

    return {
        "ticker": instrument.ticker,
        "timeframe": timeframe,
        "bars": [
            {
                "ts_utc": iso(series.ts[i]),
                "o": round(float(series.open[i]), 4),
                "h": round(float(series.high[i]), 4),
                "l": round(float(series.low[i]), 4),
                "c": round(float(series.close[i]), 4),
                "v": round(float(series.volume[i]), 0),
            }
            for i in range(len(series) - take, len(series))
        ],
        "overlays": {
            "ema20": tail(ema20), "ema50": tail(ema50), "sma200": tail(sma200),
            "rsi14": tail(rsi14), "macd": tail(macd_line),
            "macd_signal": tail(macd_signal), "macd_hist": tail(macd_hist),
            "obv": tail(obv),
        },
        "markers": sorted(markers, key=lambda m: m["ts_utc"] or ""),
        "levels": levels,
    }


@router.get("/{ticker}/signals")
def stock_signals(ticker: str, session: Session = Depends(db_session)) -> dict:
    instrument = _instrument(session, ticker)
    alerts = list(
        session.execute(
            select(BuyAlert)
            .where(BuyAlert.ticker == instrument.ticker)
            .order_by(BuyAlert.buy_ts_utc.desc())
        ).scalars()
    )
    return {"ticker": instrument.ticker, "signals": [serialize_alert(a) for a in alerts]}
