package com.equitysignal.core.model

/**
 * Domain models shared across every layer.
 *
 * Deliberately free of Android, Room and Retrofit types: these are what the UI reasons
 * about, and keeping them plain is what lets `:domain` stay a pure Kotlin module.
 *
 * Timestamps are epoch milliseconds (UTC). Formatting into America/New_York happens once,
 * at the presentation boundary.
 */

enum class AlertStatus {
    WATCHING,
    BUY_SIGNAL,
    ACTIVE,
    TARGET_1_HIT,
    TARGET_2_HIT,
    TRAILING,
    STOPPED,
    SELL_SIGNAL,
    CLOSED,
    INVALIDATED,
    UNKNOWN;

    val isOpen: Boolean
        get() = this in OPEN

    companion object {
        val OPEN = setOf(WATCHING, BUY_SIGNAL, ACTIVE, TARGET_1_HIT, TARGET_2_HIT, TRAILING)

        /** Lenient parse: an unrecognised status from a newer backend must not crash the app. */
        fun from(raw: String?): AlertStatus =
            entries.firstOrNull { it.name.equals(raw, ignoreCase = true) } ?: UNKNOWN
    }
}

enum class ScoreCategory {
    EXCEPTIONAL, STRONG_BUY, BUY, WATCH, NEUTRAL, AVOID, UNKNOWN;

    companion object {
        fun from(raw: String?): ScoreCategory =
            entries.firstOrNull { it.name.equals(raw, ignoreCase = true) } ?: UNKNOWN
    }
}

enum class MarketRegimeType {
    STRONG_BULL, BULL, NEUTRAL, RISK_OFF, BEAR, HIGH_VOLATILITY, UNKNOWN;

    companion object {
        fun from(raw: String?): MarketRegimeType =
            entries.firstOrNull { it.name.equals(raw, ignoreCase = true) } ?: UNKNOWN
    }
}

enum class MarketSessionState {
    PRE, OPEN, POST, CLOSED, HOLIDAY, UNKNOWN;

    companion object {
        fun from(raw: String?): MarketSessionState =
            entries.firstOrNull { it.name.equals(raw, ignoreCase = true) } ?: UNKNOWN
    }
}

enum class AlertEventType {
    BUY_SIGNAL, PROFIT_MILESTONE, DRAWDOWN_MILESTONE, TARGET_1_HIT, TARGET_2_HIT,
    PARTIAL_EXIT, TRAILING_STOP_UPDATED, STOP_UPDATED, THESIS_WARNING, THESIS_INVALIDATED,
    REGIME_CHANGE, SELL_SIGNAL, STOPPED, CLOSED, UNKNOWN;

    companion object {
        fun from(raw: String?): AlertEventType =
            entries.firstOrNull { it.name.equals(raw, ignoreCase = true) } ?: UNKNOWN
    }
}

/** How trustworthy a displayed price is. A cached price is never shown as live. */
enum class Freshness { LIVE, DELAYED, CACHED }

data class ComponentScores(
    val trend: Double = 0.0,
    val momentum: Double = 0.0,
    val volume: Double = 0.0,
    val breakout: Double = 0.0,
    val relativeStrength: Double = 0.0,
    val fundamental: Double = 0.0,
    val risk: Double = 0.0,
    val regime: Double = 0.0,
) {
    fun asPairs(): List<Pair<String, Double>> = listOf(
        "Trend" to trend,
        "Momentum" to momentum,
        "Volume" to volume,
        "Breakout" to breakout,
        "Rel. Strength" to relativeStrength,
        "Fundamental" to fundamental,
        "Risk" to risk,
    )
}

data class SellAlert(
    val alertUid: String,
    val buyAlertId: Long,
    val ticker: String,
    val sellTsUtc: Long,
    val sellPrice: Double,
    val entryPrice: Double,
    val fractionClosed: Double,
    val finalReturnPct: Double,
    val rMultiple: Double,
    val holdingPeriodDays: Int,
    val exitReason: String,
    val exitReasonDetail: String?,
    val maxGainPct: Double,
    val maxDrawdownPct: Double,
    val strategyVersion: String,
)

/**
 * A BUY alert and everything tracked about it — the central object of the whole app.
 *
 * The entry group (price, score, stop, targets, reasons) is immutable on the server and is
 * never rewritten here either; only the tracking group changes as the position runs.
 */
data class Alert(
    val id: Long,
    val alertUid: String,
    val ticker: String,
    val companyName: String?,
    val status: AlertStatus,
    val strategyVersion: String,

    val buyTsUtc: Long,
    val buyPrice: Double,
    val opportunityScore: Double,
    val confidence: Double,
    val probability: Double?,
    val probabilitySampleSize: Int?,
    val expectedValue: Double?,
    val rewardRisk: Double?,
    val marketRegime: String?,
    val sector: String?,
    val industry: String?,
    val breakoutType: String?,

    val stopPrice: Double,
    val currentStopPrice: Double?,
    val trailingStopPrice: Double?,
    val target1Price: Double,
    val target2Price: Double,

    val currentPrice: Double?,
    val currentReturnPct: Double,
    val maxGainPct: Double,
    val maxDrawdownPct: Double,
    val remainingFraction: Double,

    val thesisValid: Boolean,
    val thesisNotes: List<String>,
    val buyReasons: List<String>,
    val riskFactors: List<String>,
    val componentScores: ComponentScores,

    val closedTsUtc: Long?,
    val finalReturnPct: Double?,
    val holdingPeriodDays: Int?,
    val sell: SellAlert?,

    val fetchedAtUtc: Long,
    val isRead: Boolean = false,
    val isArchived: Boolean = false,
) {
    val isOpen: Boolean get() = status.isOpen
    val isClosed: Boolean get() = status == AlertStatus.CLOSED || status == AlertStatus.INVALIDATED

    /** The return to display: realised once closed, unrealised while open. */
    val displayReturnPct: Double get() = finalReturnPct ?: currentReturnPct

    /** Progress from stop (0) to target 1 (1), for the risk ladder in the detail screen. */
    val progressToTarget1: Float
        get() {
            val price = currentPrice ?: return 0f
            val span = target1Price - stopPrice
            if (span <= 0.0) return 0f
            return ((price - stopPrice) / span).coerceIn(0.0, 1.0).toFloat()
        }
}

data class AlertEvent(
    val id: Long,
    val alertUid: String,
    val tsUtc: Long,
    val type: AlertEventType,
    val price: Double?,
    val title: String,
    val detail: String?,
)

data class ScannerResult(
    val rank: Int,
    val ticker: String,
    val companyName: String?,
    val price: Double?,
    val opportunityScore: Double,
    val confidence: Double,
    val category: ScoreCategory,
    val componentScores: ComponentScores,
    val relVolume: Double?,
    val rs21: Double?,
    val atrPct: Double?,
    val suggestedEntry: Double?,
    val stopPrice: Double?,
    val target1Price: Double?,
    val target2Price: Double?,
    val rewardRisk: Double?,
    val probability: Double?,
    val probabilitySampleSize: Int?,
    val expectedValue: Double?,
    val signalReady: Boolean,
    val rulesFailed: List<String>,
    val sector: String?,
    val marketCap: Double?,
    val marketRegime: String?,
    val fetchedAtUtc: Long,
)

data class Position(
    val id: Long,
    val alertId: Long?,
    val ticker: String,
    val openedTsUtc: Long,
    val entryPrice: Double,
    val currentPrice: Double,
    val shares: Double,
    val costBasis: Double,
    val marketValue: Double,
    val unrealizedPnl: Double,
    val realizedPnl: Double,
    val returnPct: Double,
    val stopPrice: Double?,
    val target1Price: Double?,
    val target2Price: Double?,
    val riskAmount: Double?,
    val riskPctOfEquity: Double?,
    val sector: String?,
    val status: String,
)

data class PortfolioState(
    val equity: Double,
    val cash: Double,
    val positionsValue: Double,
    val openPositions: Int,
    val unrealizedPnl: Double,
    val realizedPnl: Double,
    val openRisk: Double,
    val openRiskPct: Double,
    val drawdownPct: Double,
    val sectorExposure: Map<String, Double>,
    val paperTrading: Boolean = true,
)

data class MarketStatus(
    val session: MarketSessionState,
    val serverTimeUtc: Long,
    val nextOpenUtc: Long?,
    val nextCloseUtc: Long?,
    val dataProvider: String?,
    /** True when the backend is running on generated data. The UI must say so. */
    val syntheticData: Boolean,
    val dataFresh: Boolean,
    val degraded: Boolean,
    val degradedReasons: List<String>,
    val paperTrading: Boolean,
    val fetchedAtUtc: Long,
)

data class MarketRegime(
    val regime: MarketRegimeType,
    val regimeScore: Double,
    val allowsNewBuys: Boolean,
    val breadthPct: Double?,
    val participationPct: Double?,
    val volatilityProxy: Double?,
    val spyDrawdownPct: Double?,
    val sectorParticipation: Map<String, Double>,
    val stale: Boolean,
)

data class Analytics(
    val totalBuySignals: Int,
    val openAlerts: Int,
    val closedTrades: Int,
    val winners: Int,
    val losers: Int,
    val winRate: Double?,
    val avgReturnPct: Double?,
    val medianReturnPct: Double?,
    val avgWinnerPct: Double?,
    val avgLoserPct: Double?,
    val bestTrade: TradeExtreme?,
    val worstTrade: TradeExtreme?,
    val profitFactor: Double?,
    val expectancyR: Double?,
    val maxDrawdownPct: Double?,
    val sharpe: Double?,
    val sortino: Double?,
    val avgHoldingDays: Double?,
    val targetHitRate: Double?,
    val stopRate: Double?,
    val warnings: List<String>,
    val byRegime: Map<String, GroupStat>,
    val byExitReason: Map<String, GroupStat>,
    val returnDistribution: List<DistributionBucket>,
    val portfolio: PortfolioState?,
    val fetchedAtUtc: Long,
)

data class TradeExtreme(val ticker: String, val returnPct: Double)
data class GroupStat(val trades: Int, val winRate: Double, val avgReturnPct: Double)
data class DistributionBucket(val bucket: String, val lower: Double, val count: Int)

data class EquityPoint(
    val tsUtc: Long,
    val equity: Double,
    val benchmark: Double?,
    val drawdownPct: Double,
)

data class EquityCurve(
    val benchmark: String,
    val points: List<EquityPoint>,
    val monthlyReturns: List<MonthlyReturn>,
    val returnDistribution: List<DistributionBucket>,
)

data class MonthlyReturn(val month: String, val returnPct: Double)

data class Candle(
    val tsUtc: Long,
    val open: Double,
    val high: Double,
    val low: Double,
    val close: Double,
    val volume: Double,
)

data class ChartMarker(val type: String, val tsUtc: Long, val price: Double, val alertUid: String?)

data class StockChart(
    val ticker: String,
    val candles: List<Candle>,
    val ema20: List<Double?>,
    val ema50: List<Double?>,
    val sma200: List<Double?>,
    val rsi14: List<Double?>,
    val macd: List<Double?>,
    val macdSignal: List<Double?>,
    val macdHist: List<Double?>,
    val markers: List<ChartMarker>,
    val stop: Double?,
    val target1: Double?,
    val target2: Double?,
    val entry: Double?,
)

data class StockDetail(
    val ticker: String,
    val companyName: String?,
    val exchange: String?,
    val sector: String?,
    val industry: String?,
    val marketCap: Double?,
    val lastPrice: Double?,
    val eligible: Boolean,
    val ineligibleReason: String?,
    val latestScore: ScannerResult?,
    val fetchedAtUtc: Long,
)

data class StockAnalysis(
    val ticker: String,
    val available: Boolean,
    val price: Double?,
    val opportunityScore: Double?,
    val category: ScoreCategory,
    val confidence: Double?,
    val componentScores: ComponentScores,
    val componentBreakdown: Map<String, Map<String, Double>>,
    val rulesPassed: List<String>,
    val rulesFailed: List<String>,
    val wouldBuy: Boolean,
    val buyReasons: List<String>,
    val riskFactors: List<String>,
    val probability: Double?,
    val probabilitySampleSize: Int?,
    val probabilityMethod: String?,
    val expectedValueR: Double?,
    val confidenceInterval: List<Double>,
    val entry: Double?,
    val stop: Double?,
    val target1: Double?,
    val target2: Double?,
    val rewardRisk: Double?,
    val error: String?,
)

data class BacktestRun(
    val id: Long,
    val runUid: String,
    val createdAtUtc: Long,
    val strategyVersion: String,
    val mode: String,
    val status: String,
    val error: String?,
    val startDate: String?,
    val endDate: String?,
    val universeSize: Int,
    val trades: Int,
    val winRate: Double?,
    val profitFactor: Double?,
    val expectancyR: Double?,
    val sharpe: Double?,
    val sortino: Double?,
    val maxDrawdownPct: Double?,
    val avgReturnPct: Double?,
    val avgHoldingDays: Double?,
    val targetHitRate: Double?,
    val stopRate: Double?,
    val totalReturnPct: Double?,
    val benchmarkReturnPct: Double?,
    val folds: List<BacktestFold>,
    val equityCurve: List<EquityPoint>,
    val biasWarnings: List<String>,
)

data class BacktestFold(
    val fold: Int,
    val trainRange: String,
    val testRange: String,
    val trainingSamples: Int,
    val trainExpectancy: Double?,
    val validationExpectancy: Double?,
    val testExpectancy: Double?,
    val testWinRate: Double?,
    val testTrades: Int,
)

data class SettingField(
    val key: String,
    val section: String,
    val category: String,
    val value: String,
    val default: String,
    val type: String,
    /** True when changing this would make historical alerts incomparable. */
    val versioned: Boolean,
)

data class StrategySettings(
    val strategyVersion: String,
    val description: String,
    val paperTrading: Boolean,
    val fields: List<SettingField>,
)

data class SystemStatus(
    val databaseOk: Boolean,
    val providers: List<ProviderHealth>,
    val activeProvider: String?,
    val lastScanUtc: Long?,
    val lastRegime: String?,
    val instruments: Int,
    val eligibleInstruments: Int,
    val openAlerts: Int,
    val totalAlerts: Int,
    val totalSells: Int,
    val auditErrors: Int,
    val schedulerEnabled: Boolean,
    val paperTrading: Boolean,
    val strategyVersion: String?,
)

data class ProviderHealth(val name: String, val ok: Boolean, val detail: String)

/** The Home screen's aggregate, assembled from several cached sources. */
data class DashboardSummary(
    val marketStatus: MarketStatus?,
    val regime: MarketRegime?,
    val stocksScanned: Int,
    val strongOpportunities: Int,
    val buyAlertsToday: Int,
    val sellAlertsToday: Int,
    val activeAlerts: Int,
    val openPositions: Int,
    val strategyReturnPct: Double?,
    val winRate: Double?,
    val profitFactor: Double?,
    val currentDrawdownPct: Double?,
    val topOpportunities: List<ScannerResult>,
    val recentAlerts: List<Alert>,
    val lastUpdatedUtc: Long?,
)
