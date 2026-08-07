package com.equitysignal.feature.stockdetails

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.equitysignal.core.common.Formats
import com.equitysignal.core.designsystem.Chip
import com.equitysignal.core.designsystem.EmptyState
import com.equitysignal.core.designsystem.ErrorBanner
import com.equitysignal.core.designsystem.FinancialCard
import com.equitysignal.core.designsystem.FinancialColors
import com.equitysignal.core.designsystem.LoadingState
import com.equitysignal.core.designsystem.MetricRow
import com.equitysignal.core.designsystem.NumericTextStyle
import com.equitysignal.core.designsystem.SectionLabel
import com.equitysignal.core.designsystem.StatusChip
import com.equitysignal.core.model.StockAnalysis
import com.equitysignal.core.model.StockChart

private enum class DetailTab { OVERVIEW, TECHNICAL, FUNDAMENTAL, RISK, SIGNALS }

/** Stock detail (requirement 14): chart with signal markers, then the full analysis. */
@Composable
fun StockDetailScreen(
    ticker: String,
    onAlertClick: (String) -> Unit,
    viewModel: StockDetailViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var tab by remember { mutableIntStateOf(0) }

    if (state.isLoading && state.chart == null) {
        LoadingState(label = "Loading $ticker")
        return
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        state.error?.let { item { ErrorBanner(it) } }

        item {
            FinancialCard {
                Column {
                    Text(
                        state.detail?.ticker ?: ticker,
                        style = MaterialTheme.typography.headlineMedium,
                        color = FinancialColors.OnSurface,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        state.detail?.companyName.orEmpty(),
                        style = MaterialTheme.typography.bodySmall,
                        color = FinancialColors.OnSurfaceMuted,
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        Formats.money(state.detail?.lastPrice ?: state.analysis?.price),
                        style = MaterialTheme.typography.headlineSmall.merge(NumericTextStyle),
                        color = FinancialColors.OnSurface,
                    )
                    Spacer(Modifier.height(6.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        state.detail?.sector?.let { Chip(it, FinancialColors.Neutral) }
                        if (state.detail?.eligible == false) {
                            Chip("NOT ELIGIBLE", FinancialColors.Watch, filled = true)
                        }
                    }
                    state.detail?.ineligibleReason?.let {
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "Excluded from the universe: $it",
                            style = MaterialTheme.typography.bodySmall,
                            color = FinancialColors.OnSurfaceMuted,
                        )
                    }
                }
            }
        }

        item { ChartCard(state.chart) }

        item {
            ScrollableTabRow(
                selectedTabIndex = tab,
                containerColor = FinancialColors.Background,
                edgePadding = 0.dp,
            ) {
                DetailTab.entries.forEachIndexed { index, entry ->
                    Tab(
                        selected = index == tab,
                        onClick = { tab = index },
                        text = { Text(entry.name.lowercase().replaceFirstChar { it.uppercase() }) },
                    )
                }
            }
        }

        when (DetailTab.entries[tab]) {
            DetailTab.OVERVIEW -> item { OverviewTab(state.analysis) }
            DetailTab.TECHNICAL -> item { ComponentTab(state.analysis, listOf("trend", "momentum", "volume", "breakout", "relative_strength")) }
            DetailTab.FUNDAMENTAL -> item { ComponentTab(state.analysis, listOf("fundamental")) }
            DetailTab.RISK -> item { ComponentTab(state.analysis, listOf("risk")) }
            DetailTab.SIGNALS -> {
                if (state.signals.isEmpty()) {
                    item { EmptyState("No signals for this stock yet") }
                } else {
                    item {
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            state.signals.forEach { alert ->
                                FinancialCard(
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    Row(
                                        Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                    ) {
                                        Column {
                                            Text(
                                                com.equitysignal.core.common.MarketTime.date(alert.buyTsUtc),
                                                style = MaterialTheme.typography.bodyMedium,
                                                color = FinancialColors.OnSurface,
                                            )
                                            Text(
                                                "Entry ${Formats.money(alert.buyPrice)}",
                                                style = MaterialTheme.typography.bodySmall,
                                                color = FinancialColors.OnSurfaceMuted,
                                            )
                                        }
                                        Column(horizontalAlignment = androidx.compose.ui.Alignment.End) {
                                            StatusChip(alert.status)
                                            Text(
                                                Formats.percent(alert.displayReturnPct),
                                                style = MaterialTheme.typography.bodySmall.merge(NumericTextStyle),
                                                color = com.equitysignal.core.designsystem.returnColor(alert.displayReturnPct),
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/**
 * Candlestick chart with moving-average overlays, BUY/SELL markers and the stop and
 * target lines of any open alert (requirement 14).
 */
@Composable
private fun ChartCard(chart: StockChart?) {
    FinancialCard {
        Column {
            SectionLabel("Price")
            Spacer(Modifier.height(8.dp))
            if (chart == null || chart.candles.size < 2) {
                Text(
                    "Chart data unavailable.",
                    style = MaterialTheme.typography.bodySmall,
                    color = FinancialColors.OnSurfaceMuted,
                )
                return@Column
            }

            CandlestickChart(chart, Modifier.fillMaxWidth().height(240.dp))

            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Chip("EMA20", FinancialColors.Accent)
                Chip("EMA50", FinancialColors.Watch)
                Chip("SMA200", FinancialColors.Neutral)
            }
            chart.stop?.let {
                Spacer(Modifier.height(8.dp))
                MetricRow("Stop", Formats.money(it), FinancialColors.Loss)
            }
            chart.target1?.let { MetricRow("Target 1", Formats.money(it), FinancialColors.Gain) }
            chart.target2?.let { MetricRow("Target 2", Formats.money(it), FinancialColors.Gain) }
        }
    }
}

@Composable
private fun CandlestickChart(chart: StockChart, modifier: Modifier = Modifier) {
    val candles = chart.candles
    Canvas(modifier) {
        // Scale across candle extremes and every overlay so nothing is clipped.
        val overlayValues = (chart.ema20 + chart.ema50 + chart.sma200).filterNotNull()
        val levelValues = listOfNotNull(chart.stop, chart.target1, chart.target2)
        val low = (candles.minOf { it.low }.let { listOf(it) } + overlayValues + levelValues).min()
        val high = (candles.maxOf { it.high }.let { listOf(it) } + overlayValues + levelValues).max()
        val range = (high - low).takeIf { it > 0 } ?: 1.0

        fun y(value: Double) = size.height * (1f - ((value - low) / range).toFloat())
        val slotWidth = size.width / candles.size
        val bodyWidth = (slotWidth * 0.62f).coerceAtLeast(1f)

        candles.forEachIndexed { index, candle ->
            val centerX = index * slotWidth + slotWidth / 2f
            val rising = candle.close >= candle.open
            val color = if (rising) FinancialColors.Gain else FinancialColors.Loss

            drawLine(
                color = color,
                start = Offset(centerX, y(candle.high)),
                end = Offset(centerX, y(candle.low)),
                strokeWidth = 1f,
            )
            val top = y(maxOf(candle.open, candle.close))
            val bottom = y(minOf(candle.open, candle.close))
            drawRect(
                color = color,
                topLeft = Offset(centerX - bodyWidth / 2f, top),
                size = androidx.compose.ui.geometry.Size(bodyWidth, (bottom - top).coerceAtLeast(1f)),
            )
        }

        fun drawOverlay(values: List<Double?>, color: Color) {
            val path = androidx.compose.ui.graphics.Path()
            var started = false
            values.forEachIndexed { index, value ->
                if (value == null || index >= candles.size) return@forEachIndexed
                val x = index * slotWidth + slotWidth / 2f
                if (!started) { path.moveTo(x, y(value)); started = true } else path.lineTo(x, y(value))
            }
            if (started) drawPath(path, color, style = Stroke(width = 2f))
        }
        drawOverlay(chart.ema20, FinancialColors.Accent)
        drawOverlay(chart.ema50, FinancialColors.Watch)
        drawOverlay(chart.sma200, FinancialColors.Neutral)

        val dashed = PathEffect.dashPathEffect(floatArrayOf(8f, 8f))
        fun level(value: Double?, color: Color) {
            if (value == null) return
            drawLine(color, Offset(0f, y(value)), Offset(size.width, y(value)), 1.5f, pathEffect = dashed)
        }
        level(chart.stop, FinancialColors.Loss)
        level(chart.target1, FinancialColors.Gain)
        level(chart.target2, FinancialColors.Gain)
        level(chart.entry, FinancialColors.Accent)

        // BUY and SELL markers, placed on the candle nearest each signal timestamp.
        chart.markers.forEach { marker ->
            val index = candles.indexOfFirst { it.tsUtc >= marker.tsUtc }.takeIf { it >= 0 }
                ?: return@forEach
            val x = index * slotWidth + slotWidth / 2f
            drawCircle(
                color = if (marker.type == "BUY") FinancialColors.Gain else FinancialColors.Loss,
                radius = 5f,
                center = Offset(x, y(marker.price)),
            )
        }
    }
}

@Composable
private fun OverviewTab(analysis: StockAnalysis?) {
    FinancialCard {
        Column {
            if (analysis == null || !analysis.available) {
                Text(
                    analysis?.error ?: "Analysis unavailable.",
                    style = MaterialTheme.typography.bodySmall,
                    color = FinancialColors.OnSurfaceMuted,
                )
                return@Column
            }
            SectionLabel("Current assessment")
            Spacer(Modifier.height(8.dp))
            MetricRow("Opportunity score", "${Formats.score(analysis.opportunityScore)}/100")
            MetricRow("Category", analysis.category.name.replace('_', ' '))
            MetricRow("Confidence", "${Formats.score(analysis.confidence)}/100")
            MetricRow(
                "P(target before stop)",
                Formats.probability(analysis.probability, analysis.probabilitySampleSize),
            )
            MetricRow("Expected value", "${Formats.ratio(analysis.expectedValueR)}R")
            MetricRow("Reward / risk", Formats.ratio(analysis.rewardRisk))
            MetricRow("Entry", Formats.money(analysis.entry))
            MetricRow("Stop", Formats.money(analysis.stop), FinancialColors.Loss)
            MetricRow("Target 1", Formats.money(analysis.target1), FinancialColors.Gain)

            Spacer(Modifier.height(12.dp))
            SectionLabel(if (analysis.wouldBuy) "Would signal a BUY now" else "Would not signal now")
            Spacer(Modifier.height(6.dp))
            if (analysis.wouldBuy) {
                analysis.buyReasons.forEach {
                    Text("✓ $it", style = MaterialTheme.typography.bodySmall, color = FinancialColors.Gain)
                }
            } else {
                analysis.rulesFailed.forEach {
                    Text(
                        "✗ ${it.replace('_', ' ')}",
                        style = MaterialTheme.typography.bodySmall,
                        color = FinancialColors.Loss,
                    )
                }
            }
            if (analysis.riskFactors.isNotEmpty()) {
                Spacer(Modifier.height(10.dp))
                SectionLabel("Risk factors")
                analysis.riskFactors.forEach {
                    Text("⚠ $it", style = MaterialTheme.typography.bodySmall, color = FinancialColors.Watch)
                }
            }
        }
    }
}

/** Every sub-score that fed a component, so no number on this screen is a black box. */
@Composable
private fun ComponentTab(analysis: StockAnalysis?, components: List<String>) {
    FinancialCard {
        Column {
            if (analysis == null || !analysis.available) {
                Text(
                    "Analysis unavailable.",
                    style = MaterialTheme.typography.bodySmall,
                    color = FinancialColors.OnSurfaceMuted,
                )
                return@Column
            }
            components.forEach { name ->
                val subscores = analysis.componentBreakdown[name].orEmpty()
                SectionLabel(name.replace('_', ' '))
                Spacer(Modifier.height(4.dp))
                if (subscores.isEmpty()) {
                    Text(
                        "No breakdown available.",
                        style = MaterialTheme.typography.bodySmall,
                        color = FinancialColors.OnSurfaceMuted,
                    )
                } else {
                    subscores.forEach { (key, value) ->
                        MetricRow(key.replace('_', ' '), Formats.percent(value * 100, 0, signed = false))
                    }
                }
                Spacer(Modifier.height(12.dp))
            }
        }
    }
}
