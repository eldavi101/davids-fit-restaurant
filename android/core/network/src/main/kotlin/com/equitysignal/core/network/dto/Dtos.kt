package com.equitysignal.core.network.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Wire types for the backend REST API (docs/API_SPEC.md).
 *
 * Every field is nullable or defaulted on purpose. A backend that gains a field, or that
 * legitimately has no value for one, must never crash the app — the mappers decide what a
 * missing value means, and they do it in one place.
 */

@Serializable
data class MarketStatusDto(
    val session: String? = null,
    @SerialName("server_time_utc") val serverTimeUtc: String? = null,
    @SerialName("next_open_utc") val nextOpenUtc: String? = null,
    @SerialName("next_close_utc") val nextCloseUtc: String? = null,
    @SerialName("data_provider") val dataProvider: String? = null,
    @SerialName("synthetic_data") val syntheticData: Boolean = false,
    @SerialName("data_fresh") val dataFresh: Boolean = true,
    @SerialName("last_bar_age_seconds") val lastBarAgeSeconds: Double? = null,
    val degraded: Boolean = false,
    @SerialName("degraded_reasons") val degradedReasons: List<String> = emptyList(),
    @SerialName("paper_trading") val paperTrading: Boolean = true,
)

@Serializable
data class RegimeComponentsDto(
    @SerialName("breadth_pct") val breadthPct: Double? = null,
    @SerialName("participation_pct") val participationPct: Double? = null,
    @SerialName("volatility_proxy") val volatilityProxy: Double? = null,
    @SerialName("spy_drawdown_pct") val spyDrawdownPct: Double? = null,
)

@Serializable
data class MarketRegimeDto(
    val regime: String? = null,
    @SerialName("regime_score") val regimeScore: Double = 50.0,
    @SerialName("allows_new_buys") val allowsNewBuys: Boolean = true,
    val components: RegimeComponentsDto? = null,
    @SerialName("sector_participation") val sectorParticipation: Map<String, Double> = emptyMap(),
    val stale: Boolean = false,
)

@Serializable
data class ComponentScoresDto(
    val trend: Double? = null,
    val momentum: Double? = null,
    val volume: Double? = null,
    val breakout: Double? = null,
    @SerialName("relative_strength") val relativeStrength: Double? = null,
    val fundamental: Double? = null,
    val risk: Double? = null,
)

@Serializable
data class SellAlertDto(
    val id: Long = 0,
    @SerialName("alert_uid") val alertUid: String = "",
    @SerialName("buy_alert_id") val buyAlertId: Long = 0,
    val ticker: String = "",
    @SerialName("sell_ts_utc") val sellTsUtc: String? = null,
    @SerialName("sell_price") val sellPrice: Double = 0.0,
    @SerialName("entry_price") val entryPrice: Double = 0.0,
    @SerialName("fraction_closed") val fractionClosed: Double = 1.0,
    @SerialName("final_return_pct") val finalReturnPct: Double = 0.0,
    @SerialName("r_multiple") val rMultiple: Double = 0.0,
    @SerialName("holding_period_days") val holdingPeriodDays: Int = 0,
    @SerialName("exit_reason") val exitReason: String = "",
    @SerialName("exit_reason_detail") val exitReasonDetail: String? = null,
    @SerialName("max_gain_pct") val maxGainPct: Double = 0.0,
    @SerialName("max_drawdown_pct") val maxDrawdownPct: Double = 0.0,
    @SerialName("strategy_version") val strategyVersion: String = "",
    @SerialName("buy_alert") val buyAlert: AlertDto? = null,
)

@Serializable
data class AlertDto(
    val id: Long = 0,
    @SerialName("alert_uid") val alertUid: String = "",
    val ticker: String = "",
    @SerialName("company_name") val companyName: String? = null,
    val status: String? = null,
    @SerialName("strategy_version") val strategyVersion: String = "",
    @SerialName("buy_ts_utc") val buyTsUtc: String? = null,
    @SerialName("buy_price") val buyPrice: Double = 0.0,
    @SerialName("opportunity_score") val opportunityScore: Double = 0.0,
    val confidence: Double = 0.0,
    val probability: Double? = null,
    @SerialName("probability_sample_size") val probabilitySampleSize: Int? = null,
    @SerialName("expected_value") val expectedValue: Double? = null,
    @SerialName("reward_risk") val rewardRisk: Double? = null,
    @SerialName("market_regime") val marketRegime: String? = null,
    val sector: String? = null,
    val industry: String? = null,
    @SerialName("breakout_type") val breakoutType: String? = null,
    @SerialName("stop_price") val stopPrice: Double = 0.0,
    @SerialName("current_stop_price") val currentStopPrice: Double? = null,
    @SerialName("trailing_stop_price") val trailingStopPrice: Double? = null,
    @SerialName("target1_price") val target1Price: Double = 0.0,
    @SerialName("target2_price") val target2Price: Double = 0.0,
    @SerialName("current_price") val currentPrice: Double? = null,
    @SerialName("current_return_pct") val currentReturnPct: Double = 0.0,
    @SerialName("max_gain_pct") val maxGainPct: Double = 0.0,
    @SerialName("max_drawdown_pct") val maxDrawdownPct: Double = 0.0,
    @SerialName("remaining_fraction") val remainingFraction: Double = 1.0,
    @SerialName("thesis_valid") val thesisValid: Boolean = true,
    @SerialName("thesis_notes") val thesisNotes: List<String> = emptyList(),
    @SerialName("buy_reasons") val buyReasons: List<String> = emptyList(),
    @SerialName("risk_factors") val riskFactors: List<String> = emptyList(),
    @SerialName("component_scores") val componentScores: ComponentScoresDto? = null,
    @SerialName("closed_ts_utc") val closedTsUtc: String? = null,
    @SerialName("final_return_pct") val finalReturnPct: Double? = null,
    @SerialName("holding_period_days") val holdingPeriodDays: Int? = null,
    val sell: SellAlertDto? = null,
    @SerialName("is_open") val isOpen: Boolean = true,
    @SerialName("updated_at_utc") val updatedAtUtc: String? = null,
    val timeline: List<AlertEventDto> = emptyList(),
)

@Serializable
data class AlertEventDto(
    val id: Long = 0,
    @SerialName("ts_utc") val tsUtc: String? = null,
    @SerialName("event_type") val eventType: String = "",
    val price: Double? = null,
    val title: String = "",
    val detail: String? = null,
)

@Serializable
data class AlertListDto(
    val total: Int = 0,
    val alerts: List<AlertDto> = emptyList(),
)

@Serializable
data class SellAlertListDto(
    val total: Int = 0,
    val alerts: List<SellAlertDto> = emptyList(),
)

@Serializable
data class TimelineDto(
    @SerialName("alert_uid") val alertUid: String = "",
    val ticker: String = "",
    val status: String? = null,
    val events: List<AlertEventDto> = emptyList(),
)

@Serializable
data class ScannerRowDto(
    val rank: Int = 0,
    val ticker: String = "",
    @SerialName("company_name") val companyName: String? = null,
    val price: Double? = null,
    @SerialName("opportunity_score") val opportunityScore: Double = 0.0,
    val confidence: Double = 0.0,
    val category: String? = null,
    @SerialName("trend_score") val trendScore: Double = 0.0,
    @SerialName("momentum_score") val momentumScore: Double = 0.0,
    @SerialName("volume_score") val volumeScore: Double = 0.0,
    @SerialName("breakout_score") val breakoutScore: Double = 0.0,
    @SerialName("relative_strength_score") val relativeStrengthScore: Double = 0.0,
    @SerialName("fundamental_score") val fundamentalScore: Double = 0.0,
    @SerialName("risk_score") val riskScore: Double = 0.0,
    @SerialName("regime_score") val regimeScore: Double = 0.0,
    @SerialName("rel_volume") val relVolume: Double? = null,
    @SerialName("rs_21") val rs21: Double? = null,
    @SerialName("atr_pct") val atrPct: Double? = null,
    @SerialName("suggested_entry") val suggestedEntry: Double? = null,
    @SerialName("stop_price") val stopPrice: Double? = null,
    @SerialName("target1_price") val target1Price: Double? = null,
    @SerialName("target2_price") val target2Price: Double? = null,
    @SerialName("reward_risk") val rewardRisk: Double? = null,
    val probability: Double? = null,
    @SerialName("probability_sample_size") val probabilitySampleSize: Int? = null,
    @SerialName("expected_value") val expectedValue: Double? = null,
    @SerialName("signal_ready") val signalReady: Boolean = false,
    @SerialName("rules_failed") val rulesFailed: List<String> = emptyList(),
    val sector: String? = null,
    @SerialName("market_cap") val marketCap: Double? = null,
    @SerialName("market_regime") val marketRegime: String? = null,
)

@Serializable
data class ScannerResponseDto(
    @SerialName("generated_at_utc") val generatedAtUtc: String? = null,
    val regime: String? = null,
    val total: Int = 0,
    val results: List<ScannerRowDto> = emptyList(),
)

@Serializable
data class PositionDto(
    val id: Long = 0,
    @SerialName("buy_alert_id") val buyAlertId: Long? = null,
    val ticker: String = "",
    @SerialName("opened_ts_utc") val openedTsUtc: String? = null,
    @SerialName("entry_price") val entryPrice: Double = 0.0,
    @SerialName("current_price") val currentPrice: Double = 0.0,
    val shares: Double = 0.0,
    @SerialName("cost_basis") val costBasis: Double = 0.0,
    @SerialName("market_value") val marketValue: Double = 0.0,
    @SerialName("unrealized_pnl") val unrealizedPnl: Double = 0.0,
    @SerialName("realized_pnl") val realizedPnl: Double = 0.0,
    @SerialName("return_pct") val returnPct: Double = 0.0,
    @SerialName("stop_price") val stopPrice: Double? = null,
    @SerialName("target1_price") val target1Price: Double? = null,
    @SerialName("target2_price") val target2Price: Double? = null,
    @SerialName("risk_amount") val riskAmount: Double? = null,
    @SerialName("risk_pct_of_equity") val riskPctOfEquity: Double? = null,
    val sector: String? = null,
    val status: String = "OPEN",
)

@Serializable
data class PortfolioDto(
    val equity: Double = 0.0,
    val cash: Double = 0.0,
    @SerialName("positions_value") val positionsValue: Double = 0.0,
    @SerialName("open_positions") val openPositions: Int = 0,
    @SerialName("unrealized_pnl") val unrealizedPnl: Double = 0.0,
    @SerialName("realized_pnl") val realizedPnl: Double = 0.0,
    @SerialName("open_risk") val openRisk: Double = 0.0,
    @SerialName("open_risk_pct") val openRiskPct: Double = 0.0,
    @SerialName("drawdown_pct") val drawdownPct: Double = 0.0,
    @SerialName("sector_exposure") val sectorExposure: Map<String, Double> = emptyMap(),
    @SerialName("paper_trading") val paperTrading: Boolean = true,
)

@Serializable
data class PositionsResponseDto(
    val portfolio: PortfolioDto? = null,
    val positions: List<PositionDto> = emptyList(),
)

@Serializable
data class TradeExtremeDto(val ticker: String = "", @SerialName("return_pct") val returnPct: Double = 0.0)

@Serializable
data class GroupStatDto(
    val trades: Int = 0,
    @SerialName("win_rate") val winRate: Double = 0.0,
    @SerialName("avg_return_pct") val avgReturnPct: Double = 0.0,
)

@Serializable
data class DistributionBucketDto(
    val bucket: String = "",
    val lower: Double = 0.0,
    val count: Int = 0,
)

@Serializable
data class AnalyticsDto(
    @SerialName("total_buy_signals") val totalBuySignals: Int = 0,
    @SerialName("open_alerts") val openAlerts: Int = 0,
    @SerialName("closed_trades") val closedTrades: Int = 0,
    val winners: Int = 0,
    val losers: Int = 0,
    @SerialName("win_rate") val winRate: Double? = null,
    @SerialName("avg_return_pct") val avgReturnPct: Double? = null,
    @SerialName("median_return_pct") val medianReturnPct: Double? = null,
    @SerialName("avg_winner_pct") val avgWinnerPct: Double? = null,
    @SerialName("avg_loser_pct") val avgLoserPct: Double? = null,
    @SerialName("best_trade") val bestTrade: TradeExtremeDto? = null,
    @SerialName("worst_trade") val worstTrade: TradeExtremeDto? = null,
    @SerialName("profit_factor") val profitFactor: Double? = null,
    @SerialName("expectancy_r") val expectancyR: Double? = null,
    @SerialName("max_drawdown_pct") val maxDrawdownPct: Double? = null,
    val sharpe: Double? = null,
    val sortino: Double? = null,
    @SerialName("avg_holding_days") val avgHoldingDays: Double? = null,
    @SerialName("target_hit_rate") val targetHitRate: Double? = null,
    @SerialName("stop_rate") val stopRate: Double? = null,
    val warnings: List<String> = emptyList(),
    @SerialName("by_regime") val byRegime: Map<String, GroupStatDto> = emptyMap(),
    @SerialName("by_exit_reason") val byExitReason: Map<String, GroupStatDto> = emptyMap(),
    @SerialName("return_distribution") val returnDistribution: List<DistributionBucketDto> = emptyList(),
    val portfolio: PortfolioDto? = null,
)

@Serializable
data class EquityPointDto(
    @SerialName("ts_utc") val tsUtc: String? = null,
    val equity: Double = 0.0,
    val benchmark: Double? = null,
    @SerialName("drawdown_pct") val drawdownPct: Double = 0.0,
)

@Serializable
data class MonthlyReturnDto(
    val month: String = "",
    @SerialName("return_pct") val returnPct: Double = 0.0,
)

@Serializable
data class EquityCurveDto(
    val benchmark: String = "SPY",
    val points: List<EquityPointDto> = emptyList(),
    @SerialName("monthly_returns") val monthlyReturns: List<MonthlyReturnDto> = emptyList(),
    @SerialName("return_distribution") val returnDistribution: List<DistributionBucketDto> = emptyList(),
)

@Serializable
data class CandleDto(
    @SerialName("ts_utc") val tsUtc: String? = null,
    val o: Double = 0.0,
    val h: Double = 0.0,
    val l: Double = 0.0,
    val c: Double = 0.0,
    val v: Double = 0.0,
)

@Serializable
data class OverlaysDto(
    val ema20: List<Double?> = emptyList(),
    val ema50: List<Double?> = emptyList(),
    val sma200: List<Double?> = emptyList(),
    val rsi14: List<Double?> = emptyList(),
    val macd: List<Double?> = emptyList(),
    @SerialName("macd_signal") val macdSignal: List<Double?> = emptyList(),
    @SerialName("macd_hist") val macdHist: List<Double?> = emptyList(),
)

@Serializable
data class MarkerDto(
    val type: String = "",
    @SerialName("ts_utc") val tsUtc: String? = null,
    val price: Double = 0.0,
    @SerialName("alert_uid") val alertUid: String? = null,
)

@Serializable
data class LevelsDto(
    val stop: Double? = null,
    val target1: Double? = null,
    val target2: Double? = null,
    val entry: Double? = null,
)

@Serializable
data class BarsResponseDto(
    val ticker: String = "",
    val bars: List<CandleDto> = emptyList(),
    val overlays: OverlaysDto = OverlaysDto(),
    val markers: List<MarkerDto> = emptyList(),
    val levels: LevelsDto = LevelsDto(),
)

@Serializable
data class StockProfileDto(
    val ticker: String = "",
    @SerialName("company_name") val companyName: String? = null,
    val exchange: String? = null,
    val sector: String? = null,
    val industry: String? = null,
    @SerialName("market_cap") val marketCap: Double? = null,
    @SerialName("last_price") val lastPrice: Double? = null,
    val eligible: Boolean = false,
    @SerialName("ineligible_reason") val ineligibleReason: String? = null,
    @SerialName("latest_score") val latestScore: ScannerRowDto? = null,
)

@Serializable
data class ProbabilityDto(
    val probability: Double? = null,
    @SerialName("sample_size") val sampleSize: Int? = null,
    @SerialName("historical_win_rate") val historicalWinRate: Double? = null,
    @SerialName("expected_value_r") val expectedValueR: Double? = null,
    @SerialName("confidence_interval") val confidenceInterval: List<Double> = emptyList(),
    val method: String? = null,
    val reliability: String? = null,
    val notes: List<String> = emptyList(),
)

@Serializable
data class AnalysisLevelsDto(
    val entry: Double? = null,
    val stop: Double? = null,
    val target1: Double? = null,
    val target2: Double? = null,
    @SerialName("reward_risk") val rewardRisk: Double? = null,
    @SerialName("stop_source") val stopSource: String? = null,
    val valid: Boolean = false,
    val reason: String? = null,
)

@Serializable
data class RuleDto(
    val rule: String = "",
    val passed: Boolean = false,
    val detail: String = "",
)

@Serializable
data class DecisionDto(
    val ticker: String = "",
    val decision: String = "",
    val rules: List<RuleDto> = emptyList(),
    @SerialName("rules_passed") val rulesPassed: List<String> = emptyList(),
    @SerialName("rules_failed") val rulesFailed: List<String> = emptyList(),
    val reasons: List<String> = emptyList(),
    @SerialName("risk_factors") val riskFactors: List<String> = emptyList(),
)

@Serializable
data class ScoreBreakdownDto(
    @SerialName("opportunity_score") val opportunityScore: Double = 0.0,
    val category: String? = null,
    val confidence: Double = 0.0,
    val components: Map<String, ComponentDetailDto> = emptyMap(),
    @SerialName("breakout_type") val breakoutType: String? = null,
    val notes: List<String> = emptyList(),
)

@Serializable
data class ComponentDetailDto(
    val score: Double = 0.0,
    val subscores: Map<String, Double> = emptyMap(),
    val contributions: Map<String, Double> = emptyMap(),
    val notes: List<String> = emptyList(),
)

@Serializable
data class StockAnalysisDto(
    val ticker: String = "",
    @SerialName("analysis_available") val analysisAvailable: Boolean = false,
    val price: Double? = null,
    val score: ScoreBreakdownDto? = null,
    val levels: AnalysisLevelsDto? = null,
    val probability: ProbabilityDto? = null,
    val decision: DecisionDto? = null,
    @SerialName("would_buy") val wouldBuy: Boolean = false,
    @SerialName("buy_reasons") val buyReasons: List<String> = emptyList(),
    @SerialName("risk_factors") val riskFactors: List<String> = emptyList(),
    val error: String? = null,
)

@Serializable
data class BacktestMetricsDto(
    val trades: Int = 0,
    @SerialName("win_rate") val winRate: Double? = null,
    @SerialName("profit_factor") val profitFactor: Double? = null,
    @SerialName("expectancy_r") val expectancyR: Double? = null,
    val sharpe: Double? = null,
    val sortino: Double? = null,
    @SerialName("max_drawdown_pct") val maxDrawdownPct: Double? = null,
    @SerialName("avg_return_pct") val avgReturnPct: Double? = null,
    @SerialName("avg_holding_days") val avgHoldingDays: Double? = null,
    @SerialName("target_hit_rate") val targetHitRate: Double? = null,
    @SerialName("stop_rate") val stopRate: Double? = null,
    @SerialName("total_return_pct") val totalReturnPct: Double? = null,
    @SerialName("benchmark_return_pct") val benchmarkReturnPct: Double? = null,
)

@Serializable
data class FoldRangeDto(val start: String = "", val end: String = "")

@Serializable
data class FoldDto(
    val fold: Int = 0,
    val train: FoldRangeDto = FoldRangeDto(),
    val test: FoldRangeDto = FoldRangeDto(),
    @SerialName("training_samples") val trainingSamples: Int = 0,
    @SerialName("train_metrics") val trainMetrics: BacktestMetricsDto? = null,
    @SerialName("validation_metrics") val validationMetrics: BacktestMetricsDto? = null,
    @SerialName("test_metrics") val testMetrics: BacktestMetricsDto? = null,
)

@Serializable
data class BacktestRunDto(
    val id: Long = 0,
    @SerialName("run_uid") val runUid: String = "",
    @SerialName("created_at_utc") val createdAtUtc: String? = null,
    @SerialName("strategy_version") val strategyVersion: String = "",
    val mode: String = "BACKTEST",
    val status: String = "QUEUED",
    val error: String? = null,
    @SerialName("start_date") val startDate: String? = null,
    @SerialName("end_date") val endDate: String? = null,
    @SerialName("universe_size") val universeSize: Int = 0,
    val metrics: BacktestMetricsDto = BacktestMetricsDto(),
    val folds: List<FoldDto> = emptyList(),
    @SerialName("equity_curve") val equityCurve: List<EquityPointDto> = emptyList(),
    @SerialName("bias_warnings") val biasWarnings: List<String> = emptyList(),
)

@Serializable
data class BacktestListDto(val runs: List<BacktestRunDto> = emptyList())

@Serializable
data class BacktestRequestDto(
    val mode: String = "BACKTEST",
    @SerialName("start_date") val startDate: String? = null,
    @SerialName("end_date") val endDate: String? = null,
    val universe: List<String>? = null,
    @SerialName("initial_equity") val initialEquity: Double = 100_000.0,
    @SerialName("include_sensitivity") val includeSensitivity: Boolean = false,
)

@Serializable
data class BacktestAcceptedDto(
    @SerialName("run_uid") val runUid: String = "",
    val id: Long = 0,
    val status: String = "QUEUED",
)

@Serializable
data class SettingFieldDto(
    val value: kotlinx.serialization.json.JsonElement? = null,
    val default: kotlinx.serialization.json.JsonElement? = null,
    val type: String = "",
)

@Serializable
data class SettingSectionDto(
    val category: String = "",
    val versioned: Boolean = false,
    val fields: Map<String, SettingFieldDto> = emptyMap(),
)

@Serializable
data class SettingsDto(
    @SerialName("strategy_version") val strategyVersion: String = "",
    val description: String = "",
    @SerialName("paper_trading") val paperTrading: Boolean = true,
    val sections: Map<String, SettingSectionDto> = emptyMap(),
)

@Serializable
data class SettingsUpdateDto(
    val updates: Map<String, kotlinx.serialization.json.JsonElement> = emptyMap(),
    @SerialName("create_version") val createVersion: Boolean = false,
)

@Serializable
data class ProviderHealthDto(
    val name: String = "",
    val ok: Boolean = false,
    val detail: String = "",
)

@Serializable
data class DatabaseHealthDto(val ok: Boolean = false, val detail: String = "")

@Serializable
data class SystemStatusDto(
    val database: DatabaseHealthDto = DatabaseHealthDto(),
    val providers: List<ProviderHealthDto> = emptyList(),
    @SerialName("active_provider") val activeProvider: String? = null,
    @SerialName("last_scan_utc") val lastScanUtc: String? = null,
    @SerialName("last_regime") val lastRegime: String? = null,
    val instruments: Int = 0,
    @SerialName("eligible_instruments") val eligibleInstruments: Int = 0,
    @SerialName("open_alerts") val openAlerts: Int = 0,
    @SerialName("total_alerts") val totalAlerts: Int = 0,
    @SerialName("total_sells") val totalSells: Int = 0,
    @SerialName("audit_errors") val auditErrors: Int = 0,
    @SerialName("scheduler_enabled") val schedulerEnabled: Boolean = false,
    @SerialName("paper_trading") val paperTrading: Boolean = true,
    @SerialName("strategy_version") val strategyVersion: String? = null,
)

/** The single payload the background sync worker requests. */
@Serializable
data class SyncResponseDto(
    @SerialName("server_time_utc") val serverTimeUtc: String? = null,
    @SerialName("next_since") val nextSince: String? = null,
    @SerialName("market_status") val marketStatus: MarketStatusDto? = null,
    val regime: MarketRegimeDto? = null,
    val alerts: List<AlertDto> = emptyList(),
    @SerialName("sell_alerts") val sellAlerts: List<SellAlertDto> = emptyList(),
    val positions: List<PositionDto> = emptyList(),
    val portfolio: PortfolioDto? = null,
    val scanner: List<ScannerRowDto> = emptyList(),
    val analytics: AnalyticsDto? = null,
)
