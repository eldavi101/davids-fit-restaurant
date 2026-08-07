package com.equitysignal.feature.analytics

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import com.equitysignal.core.designsystem.FinancialColors

/**
 * Two normalised series on one axis.
 *
 * Both lines are scaled to the *same* min/max so the comparison is honest — scaling each
 * to its own range would make any strategy look like it tracks its benchmark.
 */
@Composable
fun SparklineComparison(
    strategy: List<Double>,
    benchmark: List<Double>,
    modifier: Modifier = Modifier,
) {
    if (strategy.size < 2) return

    Canvas(modifier) {
        val all = strategy + benchmark
        val minValue = all.min()
        val maxValue = all.max()
        val range = (maxValue - minValue).takeIf { it > 0.0 } ?: 1.0

        fun path(values: List<Double>): Path? {
            if (values.size < 2) return null
            val stepX = size.width / (values.size - 1).toFloat()
            return Path().apply {
                values.forEachIndexed { index, value ->
                    val x = index * stepX
                    val y = size.height * (1f - ((value - minValue) / range).toFloat())
                    if (index == 0) moveTo(x, y) else lineTo(x, y)
                }
            }
        }

        path(benchmark)?.let {
            drawPath(it, color = FinancialColors.Neutral, style = Stroke(width = 2f))
        }
        path(strategy)?.let {
            drawPath(it, color = FinancialColors.Accent, style = Stroke(width = 3f))
        }

        // Baseline at the starting equity so gains and losses are visually anchored.
        val startY = size.height * (1f - ((strategy.first() - minValue) / range).toFloat())
        drawLine(
            color = FinancialColors.Outline,
            start = Offset(0f, startY),
            end = Offset(size.width, startY),
            strokeWidth = 1f,
        )
    }
}
