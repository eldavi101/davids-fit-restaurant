package com.equitysignal.core.network

import com.equitysignal.core.common.MarketTime
import com.equitysignal.core.model.Alert
import com.equitysignal.core.model.AlertEvent
import com.equitysignal.core.model.AlertEventType
import com.equitysignal.core.model.AlertStatus
import com.equitysignal.core.model.Analytics
import com.equitysignal.core.model.BacktestFold
import com.equitysignal.core.model.BacktestRun
import com.equitysignal.core.model.Candle
import com.equitysignal.core.model.ChartMarker
import com.equitysignal.core.model.ComponentScores
import com.equitysignal.core.model.DistributionBucket
import com.equitysignal.core.model.EquityCurve
import com.equitysignal.core.model.EquityPoint
import com.equitysignal.core.model.GroupStat
import com.equitysignal.core.model.MarketRegime
import com.equitysignal.core.model.MarketRegimeType
import com.equitysignal.core.model.MarketSessionState
import com.equitysignal.core.model.MarketStatus
import com.equitysignal.core.model.MonthlyReturn
import com.equitysignal.core.model.PortfolioState
import com.equitysignal.core.model.Position
import com.equitysignal.core.model.ProviderHealth
import com.equitysignal.core.model.ScannerResult
import com.equitysignal.core.model.ScoreCategory
import com.equitysignal.core.model.SellAlert
import com.equitysignal.core.model.SettingField
import com.equitysignal.core.model.StockAnalysis
import com.equitysignal.core.model.StockChart
import com.equitysignal.core.model.StockDetail
import com.equitysignal.core.model.StrategySettings
import com.equitysignal.core.model.SystemStatus
import com.equitysignal.core.model.TradeExtreme
import com.equitysignal.core.network.dto.AlertDto
import com.equitysignal.core.network.dto.AlertEventDto
import com.equitysignal.core.network.dto.AnalyticsDto
import com.equitysignal.core.network.dto.BacktestRunDto
import com.equitysignal.core.network.dto.BarsResponseDto
import com.equitysignal.core.network.dto.ComponentScoresDto
import com.equitysignal.core.network.dto.DistributionBucketDto
import com.equitysignal.core.network.dto.EquityCurveDto
import com.equitysignal.core.network.dto.EquityPointDto
import com.equitysignal.core.network.dto.GroupStatDto
import com.equitysignal.core.network.dto.MarketRegimeDto
import com.equitysignal.core.network.dto.MarketStatusDto
import com.equitysignal.core.network.dto.PortfolioDto
import com.equitysignal.core.network.dto.PositionDto
import com.equitysignal.core.network.dto.ScannerRowDto
import com.equitysignal.core.network.dto.SellAlertDto
import com.equitysignal.core.network.dto.SettingsDto
import com.equitysignal.core.network.dto.StockAnalysisDto
import com.equitysignal.core.network.dto.StockProfileDto
import com.equitysignal.core.network.dto.SystemStatusDto
import kotlinx.serialization.json.JsonPrimitive

/**
 * DTO → domain mapping.
 *
 * Every conversion is total: a missing or unrecognised value maps to a defined default
 * rather than throwing, so one odd row from the backend cannot blank an entire screen.
 * `fetchedAt` is stamped here because provenance is what lets the UI honestly label data
 * as live, delayed or cached.
 */

private fun ts(value: String?): Long? = MarketTime.parseIso(value)
private fun tsOrNow(value: String?, now: Long): Long = ts(value) ?: now

fun ComponentScoresDto?.toModel(regime: Double = 0.0): ComponentScores = ComponentScores(
    trend = this?.trend ?: 0.0,
    momentum = this?.momentum ?: 0.0,
    volume = this?.volume ?: 0.0,
    breakout = this?.breakout ?: 0.0,
    relativeStrength = this?.relativeStrength ?: 0.0,
    fundamental = this?.fundamental ?: 0.0,
    risk = this?.risk ?: 0.0,
    regime = regime,
)

fun SellAlertDto.toModel(): SellAlert = SellAlert(
    alertUid = alertUid,
    buyAlertId = buyAlertId,
    ticker = ticker,
    sellTsUtc = ts(sellTsUtc) ?: 0L,
    sellPrice = sellPrice,
    entryPrice = entryPrice,
    fractionClosed = fractionClosed,
    finalReturnPct = finalReturnPct,
    rMultiple = rMultiple,
    holdingPeriodDays = holdingPeriodDays,
    exitReason = exitReason,
    exitReasonDetail = exitReasonDetail,
    maxGainPct = maxGainPct,
    maxDrawdownPct = maxDrawdownPct,
    strategyVersion = strategyVersion,
)

fun AlertDto.toModel(now: Long = System.currentTimeMillis()): Alert = Alert(
    id = id,
    alertUid = alertUid,
    ticker = ticker,
    companyName = companyName,
    status = AlertStatus.from(status),
    strategyVersion = strategyVersion,
    buyTsUtc = tsOrNow(buyTsUtc, now),
    buyPrice = buyPrice,
    opportunityScore = opportunityScore,
    confidence = confidence,
    probability = probability,
    probabilitySampleSize = probabilitySampleSize,
    expectedValue = expectedValue,
    rewardRisk = rewardRisk,
    marketRegime = marketRegime,
    sector = sector,
    industry = industry,
    breakoutType = breakoutType,
    stopPrice = stopPrice,
    currentStopPrice = currentStopPrice,
    trailingStopPrice = trailingStopPrice,
    target1Price = target1Price,
    target2Price = target2Price,
    currentPrice = currentPrice,
    currentReturnPct = currentReturnPct,
    maxGainPct = maxGainPct,
    maxDrawdownPct = maxDrawdownPct,
    remainingFraction = remainingFraction,
    thesisValid = thesisValid,
    thesisNotes = thesisNotes,
    buyReasons = buyReasons,
    riskFactors = riskFactors,
    componentScores = componentScores.toModel(),
    closedTsUtc = ts(closedTsUtc),
    finalReturnPct = finalReturnPct,
    holdingPeriodDays = holdingPeriodDays,
    sell = sell?.toModel(),
    fetchedAtUtc = now,
)

fun AlertEventDto.toModel(alertUid: String): AlertEvent = AlertEvent(
    id = id,
    alertUid = alertUid,
    tsUtc = ts(tsUtc) ?: 0L,
    type = AlertEventType.from(eventType),
    price = price,
    title = title,
    detail = detail,
)

fun ScannerRowDto.toModel(now: Long = System.currentTimeMillis()): ScannerResult = ScannerResult(
    rank = rank,
    ticker = ticker,
    companyName = companyName,
    price = price,
    opportunityScore = opportunityScore,
    confidence = confidence,
    category = ScoreCategory.from(category),
    componentScores = ComponentScores(
        trend = trendScore,
        momentum = momentumScore,
        volume = volumeScore,
        breakout = breakoutScore,
        relativeStrength = relativeStrengthScore,
        fundamental = fundamentalScore,
        risk = riskScore,
        regime = regimeScore,
    ),
    relVolume = relVolume,
    rs21 = rs21,
    atrPct = atrPct,
    suggestedEntry = suggestedEntry,
    stopPrice = stopPrice,
    target1Price = target1Price,
    target2Price = target2Price,
    rewardRisk = rewardRisk,
    probability = probability,
    probabilitySampleSize = probabilitySampleSize,
    expectedValue = expectedValue,
    signalReady = signalReady,
    rulesFailed = rulesFailed,
    sector = sector,
    marketCap = marketCap,
    marketRegime = marketRegime,
    fetchedAtUtc = now,
)

fun MarketStatusDto.toModel(now: Long = System.currentTimeMillis()): MarketStatus = MarketStatus(
    session = MarketSessionState.from(session),
    serverTimeUtc = tsOrNow(serverTimeUtc, now),
    nextOpenUtc = ts(nextOpenUtc),
    nextCloseUtc = ts(nextCloseUtc),
    dataProvider = dataProvider,
    syntheticData = syntheticData,
    dataFresh = dataFresh,
    degraded = degraded,
    degradedReasons = degradedReasons,
    paperTrading = paperTrading,
    fetchedAtUtc = now,
)

fun MarketRegimeDto.toModel(): MarketRegime = MarketRegime(
    regime = MarketRegimeType.from(regime),
    regimeScore = regimeScore,
    allowsNewBuys = allowsNewBuys,
    breadthPct = components?.breadthPct,
    participationPct = components?.participationPct,
    volatilityProxy = components?.volatilityProxy,
    spyDrawdownPct = components?.spyDrawdownPct,
    sectorParticipation = sectorParticipation,
    stale = stale,
)

fun PositionDto.toModel(): Position = Position(
    id = id,
    alertId = buyAlertId,
    ticker = ticker,
    openedTsUtc = ts(openedTsUtc) ?: 0L,
    entryPrice = entryPrice,
    currentPrice = currentPrice,
    shares = shares,
    costBasis = costBasis,
    marketValue = marketValue,
    unrealizedPnl = unrealizedPnl,
    realizedPnl = realizedPnl,
    returnPct = returnPct,
    stopPrice = stopPrice,
    target1Price = target1Price,
    target2Price = target2Price,
    riskAmount = riskAmount,
    riskPctOfEquity = riskPctOfEquity,
    sector = sector,
    status = status,
)

fun PortfolioDto.toModel(): PortfolioState = PortfolioState(
    equity = equity,
    cash = cash,
    positionsValue = positionsValue,
    openPositions = openPositions,
    unrealizedPnl = unrealizedPnl,
    realizedPnl = realizedPnl,
    openRisk = openRisk,
    openRiskPct = openRiskPct,
    drawdownPct = drawdownPct,
    sectorExposure = sectorExposure,
    paperTrading = paperTrading,
)

private fun GroupStatDto.toModel() = GroupStat(trades, winRate, avgReturnPct)
private fun DistributionBucketDto.toModel() = DistributionBucket(bucket, lower, count)

fun AnalyticsDto.toModel(now: Long = System.currentTimeMillis()): Analytics = Analytics(
    totalBuySignals = totalBuySignals,
    openAlerts = openAlerts,
    closedTrades = closedTrades,
    winners = winners,
    losers = losers,
    winRate = winRate,
    avgReturnPct = avgReturnPct,
    medianReturnPct = medianReturnPct,
    avgWinnerPct = avgWinnerPct,
    avgLoserPct = avgLoserPct,
    bestTrade = bestTrade?.let { TradeExtreme(it.ticker, it.returnPct) },
    worstTrade = worstTrade?.let { TradeExtreme(it.ticker, it.returnPct) },
    profitFactor = profitFactor,
    expectancyR = expectancyR,
    maxDrawdownPct = maxDrawdownPct,
    sharpe = sharpe,
    sortino = sortino,
    avgHoldingDays = avgHoldingDays,
    targetHitRate = targetHitRate,
    stopRate = stopRate,
    warnings = warnings,
    byRegime = byRegime.mapValues { it.value.toModel() },
    byExitReason = byExitReason.mapValues { it.value.toModel() },
    returnDistribution = returnDistribution.map { it.toModel() },
    portfolio = portfolio?.toModel(),
    fetchedAtUtc = now,
)

private fun EquityPointDto.toModel() = EquityPoint(ts(tsUtc) ?: 0L, equity, benchmark, drawdownPct)

fun EquityCurveDto.toModel(): EquityCurve = EquityCurve(
    benchmark = benchmark,
    points = points.map { it.toModel() },
    monthlyReturns = monthlyReturns.map { MonthlyReturn(it.month, it.returnPct) },
    returnDistribution = returnDistribution.map { it.toModel() },
)

fun BarsResponseDto.toModel(): StockChart {
    val candles = bars.map { Candle(ts(it.tsUtc) ?: 0L, it.o, it.h, it.l, it.c, it.v) }
    return StockChart(
        ticker = ticker,
        candles = candles,
        ema20 = overlays.ema20,
        ema50 = overlays.ema50,
        sma200 = overlays.sma200,
        rsi14 = overlays.rsi14,
        macd = overlays.macd,
        macdSignal = overlays.macdSignal,
        macdHist = overlays.macdHist,
        markers = markers.map { ChartMarker(it.type, ts(it.tsUtc) ?: 0L, it.price, it.alertUid) },
        stop = levels.stop,
        target1 = levels.target1,
        target2 = levels.target2,
        entry = levels.entry,
    )
}

fun StockProfileDto.toModel(now: Long = System.currentTimeMillis()): StockDetail = StockDetail(
    ticker = ticker,
    companyName = companyName,
    exchange = exchange,
    sector = sector,
    industry = industry,
    marketCap = marketCap,
    lastPrice = lastPrice,
    eligible = eligible,
    ineligibleReason = ineligibleReason,
    latestScore = latestScore?.toModel(now),
    fetchedAtUtc = now,
)

fun StockAnalysisDto.toModel(): StockAnalysis {
    val components = score?.components.orEmpty()
    return StockAnalysis(
        ticker = ticker,
        available = analysisAvailable,
        price = price,
        opportunityScore = score?.opportunityScore,
        category = ScoreCategory.from(score?.category),
        confidence = score?.confidence,
        componentScores = ComponentScores(
            trend = components["trend"]?.score ?: 0.0,
            momentum = components["momentum"]?.score ?: 0.0,
            volume = components["volume"]?.score ?: 0.0,
            breakout = components["breakout"]?.score ?: 0.0,
            relativeStrength = components["relative_strength"]?.score ?: 0.0,
            fundamental = components["fundamental"]?.score ?: 0.0,
            risk = components["risk"]?.score ?: 0.0,
        ),
        componentBreakdown = components.mapValues { it.value.subscores },
        rulesPassed = decision?.rulesPassed.orEmpty(),
        rulesFailed = decision?.rulesFailed.orEmpty(),
        wouldBuy = wouldBuy,
        buyReasons = buyReasons,
        riskFactors = riskFactors,
        probability = probability?.probability,
        probabilitySampleSize = probability?.sampleSize,
        probabilityMethod = probability?.method,
        expectedValueR = probability?.expectedValueR,
        confidenceInterval = probability?.confidenceInterval.orEmpty(),
        entry = levels?.entry,
        stop = levels?.stop,
        target1 = levels?.target1,
        target2 = levels?.target2,
        rewardRisk = levels?.rewardRisk,
        error = error,
    )
}

fun BacktestRunDto.toModel(): BacktestRun = BacktestRun(
    id = id,
    runUid = runUid,
    createdAtUtc = ts(createdAtUtc) ?: 0L,
    strategyVersion = strategyVersion,
    mode = mode,
    status = status,
    error = error,
    startDate = startDate,
    endDate = endDate,
    universeSize = universeSize,
    trades = metrics.trades,
    winRate = metrics.winRate,
    profitFactor = metrics.profitFactor,
    expectancyR = metrics.expectancyR,
    sharpe = metrics.sharpe,
    sortino = metrics.sortino,
    maxDrawdownPct = metrics.maxDrawdownPct,
    avgReturnPct = metrics.avgReturnPct,
    avgHoldingDays = metrics.avgHoldingDays,
    targetHitRate = metrics.targetHitRate,
    stopRate = metrics.stopRate,
    totalReturnPct = metrics.totalReturnPct,
    benchmarkReturnPct = metrics.benchmarkReturnPct,
    folds = folds.map {
        BacktestFold(
            fold = it.fold,
            trainRange = "${it.train.start} → ${it.train.end}",
            testRange = "${it.test.start} → ${it.test.end}",
            trainingSamples = it.trainingSamples,
            trainExpectancy = it.trainMetrics?.expectancyR,
            validationExpectancy = it.validationMetrics?.expectancyR,
            testExpectancy = it.testMetrics?.expectancyR,
            testWinRate = it.testMetrics?.winRate,
            testTrades = it.testMetrics?.trades ?: 0,
        )
    },
    equityCurve = equityCurve.map { it.toModel() },
    biasWarnings = biasWarnings,
)

fun SettingsDto.toModel(): StrategySettings = StrategySettings(
    strategyVersion = strategyVersion,
    description = description,
    paperTrading = paperTrading,
    fields = sections.flatMap { (sectionName, section) ->
        section.fields.map { (key, field) ->
            SettingField(
                key = key,
                section = sectionName,
                category = section.category,
                value = field.value.render(),
                default = field.default.render(),
                type = field.type,
                versioned = section.versioned,
            )
        }
    }.sortedWith(compareBy({ it.category }, { it.section }, { it.key })),
)

private fun kotlinx.serialization.json.JsonElement?.render(): String = when (this) {
    null -> ""
    is JsonPrimitive -> content
    else -> toString()
}

fun SystemStatusDto.toModel(): SystemStatus = SystemStatus(
    databaseOk = database.ok,
    providers = providers.map { ProviderHealth(it.name, it.ok, it.detail) },
    activeProvider = activeProvider,
    lastScanUtc = ts(lastScanUtc),
    lastRegime = lastRegime,
    instruments = instruments,
    eligibleInstruments = eligibleInstruments,
    openAlerts = openAlerts,
    totalAlerts = totalAlerts,
    totalSells = totalSells,
    auditErrors = auditErrors,
    schedulerEnabled = schedulerEnabled,
    paperTrading = paperTrading,
    strategyVersion = strategyVersion,
)
