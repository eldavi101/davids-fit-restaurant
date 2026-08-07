package com.equitysignal.core.network

import com.equitysignal.core.network.dto.AlertDto
import com.equitysignal.core.network.dto.AlertListDto
import com.equitysignal.core.network.dto.AnalyticsDto
import com.equitysignal.core.network.dto.BacktestAcceptedDto
import com.equitysignal.core.network.dto.BacktestListDto
import com.equitysignal.core.network.dto.BacktestRequestDto
import com.equitysignal.core.network.dto.BacktestRunDto
import com.equitysignal.core.network.dto.BarsResponseDto
import com.equitysignal.core.network.dto.EquityCurveDto
import com.equitysignal.core.network.dto.MarketRegimeDto
import com.equitysignal.core.network.dto.MarketStatusDto
import com.equitysignal.core.network.dto.PositionsResponseDto
import com.equitysignal.core.network.dto.ScannerResponseDto
import com.equitysignal.core.network.dto.SellAlertListDto
import com.equitysignal.core.network.dto.SettingsDto
import com.equitysignal.core.network.dto.SettingsUpdateDto
import com.equitysignal.core.network.dto.StockAnalysisDto
import com.equitysignal.core.network.dto.StockProfileDto
import com.equitysignal.core.network.dto.SyncResponseDto
import com.equitysignal.core.network.dto.SystemStatusDto
import com.equitysignal.core.network.dto.TimelineDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * The backend contract (docs/API_SPEC.md).
 *
 * Note what is absent: there is no endpoint to delete an alert. Alerts are permanent, and
 * the API surface reflects that rather than relying on the client to behave.
 */
interface EquitySignalApi {

    // --- market -----------------------------------------------------------------------
    @GET("market/status")
    suspend fun marketStatus(): MarketStatusDto

    @GET("market/regime")
    suspend fun marketRegime(): MarketRegimeDto

    // --- scanner ----------------------------------------------------------------------
    @GET("scanner")
    suspend fun scanner(
        @Query("min_score") minScore: Double? = null,
        @Query("sector") sector: String? = null,
        @Query("category") category: String? = null,
        @Query("min_market_cap") minMarketCap: Double? = null,
        @Query("min_price") minPrice: Double? = null,
        @Query("max_price") maxPrice: Double? = null,
        @Query("min_rel_volume") minRelVolume: Double? = null,
        @Query("min_risk_score") minRiskScore: Double? = null,
        @Query("signal_ready") signalReady: Boolean? = null,
        @Query("regime") regime: String? = null,
        @Query("search") search: String? = null,
        @Query("sort") sort: String = "score",
        @Query("order") order: String = "desc",
        @Query("limit") limit: Int = 100,
        @Query("offset") offset: Int = 0,
    ): ScannerResponseDto

    // --- stocks -----------------------------------------------------------------------
    @GET("stocks/{ticker}")
    suspend fun stock(@Path("ticker") ticker: String): StockProfileDto

    @GET("stocks/{ticker}/analysis")
    suspend fun stockAnalysis(@Path("ticker") ticker: String): StockAnalysisDto

    @GET("stocks/{ticker}/bars")
    suspend fun stockBars(
        @Path("ticker") ticker: String,
        @Query("limit") limit: Int = 300,
        @Query("timeframe") timeframe: String = "1d",
    ): BarsResponseDto

    @GET("stocks/{ticker}/signals")
    suspend fun stockSignals(@Path("ticker") ticker: String): AlertListDto

    // --- alerts -----------------------------------------------------------------------
    @GET("alerts")
    suspend fun alerts(
        @Query("status") status: String? = null,
        @Query("ticker") ticker: String? = null,
        @Query("since") since: String? = null,
        @Query("limit") limit: Int = 200,
        @Query("offset") offset: Int = 0,
    ): AlertListDto

    @GET("alerts/active")
    suspend fun activeAlerts(@Query("limit") limit: Int = 200): AlertListDto

    @GET("alerts/closed")
    suspend fun closedAlerts(@Query("limit") limit: Int = 200): AlertListDto

    @GET("alerts/sell")
    suspend fun sellAlerts(
        @Query("since") since: String? = null,
        @Query("limit") limit: Int = 200,
    ): SellAlertListDto

    @GET("alerts/{identifier}")
    suspend fun alert(@Path("identifier") identifier: String): AlertDto

    @GET("alerts/{identifier}/timeline")
    suspend fun timeline(@Path("identifier") identifier: String): TimelineDto

    // --- portfolio --------------------------------------------------------------------
    @GET("positions")
    suspend fun positions(@Query("status") status: String = "OPEN"): PositionsResponseDto

    @GET("history")
    suspend fun history(
        @Query("outcome") outcome: String = "all",
        @Query("ticker") ticker: String? = null,
        @Query("sector") sector: String? = null,
        @Query("strategy_version") strategyVersion: String? = null,
        @Query("min_return") minReturn: Double? = null,
        @Query("max_return") maxReturn: Double? = null,
        @Query("limit") limit: Int = 200,
        @Query("offset") offset: Int = 0,
    ): AlertListDto

    @GET("analytics")
    suspend fun analytics(): AnalyticsDto

    @GET("performance/equity-curve")
    suspend fun equityCurve(@Query("benchmark") benchmark: String = "SPY"): EquityCurveDto

    // --- backtesting ------------------------------------------------------------------
    @POST("backtests")
    suspend fun startBacktest(@Body request: BacktestRequestDto): BacktestAcceptedDto

    @GET("backtests")
    suspend fun backtests(@Query("limit") limit: Int = 50): BacktestListDto

    @GET("backtests/{identifier}")
    suspend fun backtest(@Path("identifier") identifier: String): BacktestRunDto

    // --- settings ---------------------------------------------------------------------
    @GET("settings")
    suspend fun settings(): SettingsDto

    @PUT("settings")
    suspend fun updateSettings(@Body body: SettingsUpdateDto): SettingsDto

    // --- system -----------------------------------------------------------------------
    @GET("system/status")
    suspend fun systemStatus(): SystemStatusDto

    @POST("system/scan")
    suspend fun triggerScan(): Map<String, kotlinx.serialization.json.JsonElement>

    /** One round trip for the background sync worker. */
    @GET("sync")
    suspend fun sync(@Query("since") since: String? = null): SyncResponseDto
}
