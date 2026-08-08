package com.equitysignal.core.designsystem

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * A dark-first institutional palette (requirement 54).
 *
 * Colours are *semantic*, not decorative: `gain`/`loss` mean direction of money, and the
 * status colours mean one thing everywhere in the app. Nothing here is picked to look
 * pretty at the cost of being unambiguous on a trading screen.
 */
object FinancialColors {
    val Gain = Color(0xFF17C964)
    val GainDim = Color(0xFF0E7A3C)
    val Loss = Color(0xFFF31260)
    val LossDim = Color(0xFF8E0B38)
    val Neutral = Color(0xFF8B93A7)

    val Background = Color(0xFF0E1117)
    val Surface = Color(0xFF161B24)
    val SurfaceElevated = Color(0xFF1D2430)
    val Outline = Color(0xFF2A3341)

    val Accent = Color(0xFF3B82F6)
    val AccentMuted = Color(0xFF1E3A5F)

    val Exceptional = Color(0xFF9B5DE5)
    val StrongBuy = Color(0xFF17C964)
    val Buy = Color(0xFF3DBE7C)
    val Watch = Color(0xFFF5A524)
    val NeutralChip = Color(0xFF6B7280)
    val Avoid = Color(0xFFF31260)

    val Active = Color(0xFF3B82F6)
    val Closed = Color(0xFF64748B)
    val Stopped = Color(0xFFF31260)
    val Trailing = Color(0xFF06B6D4)

    val OnSurface = Color(0xFFE6EAF2)
    val OnSurfaceMuted = Color(0xFF9AA4B8)
}

/** Extra roles Material 3 has no slot for. */
data class FinancialColorScheme(
    val gain: Color,
    val loss: Color,
    val neutral: Color,
    val surfaceElevated: Color,
    val onSurfaceMuted: Color,
    val outlineSubtle: Color,
)

val LocalFinancialColors = staticCompositionLocalOf {
    FinancialColorScheme(
        gain = FinancialColors.Gain,
        loss = FinancialColors.Loss,
        neutral = FinancialColors.Neutral,
        surfaceElevated = FinancialColors.SurfaceElevated,
        onSurfaceMuted = FinancialColors.OnSurfaceMuted,
        outlineSubtle = FinancialColors.Outline,
    )
}

private val DarkScheme = darkColorScheme(
    primary = FinancialColors.Accent,
    onPrimary = Color.White,
    primaryContainer = FinancialColors.AccentMuted,
    onPrimaryContainer = Color(0xFFD6E4FF),
    secondary = FinancialColors.Trailing,
    background = FinancialColors.Background,
    onBackground = FinancialColors.OnSurface,
    surface = FinancialColors.Surface,
    onSurface = FinancialColors.OnSurface,
    surfaceVariant = FinancialColors.SurfaceElevated,
    onSurfaceVariant = FinancialColors.OnSurfaceMuted,
    outline = FinancialColors.Outline,
    error = FinancialColors.Loss,
    onError = Color.White,
)

// A light scheme exists so the app never inherits an unstyled surface if a user forces
// light mode, but the product is designed dark-first.
private val LightScheme = lightColorScheme(
    primary = Color(0xFF1D4ED8),
    background = Color(0xFFF7F8FA),
    surface = Color.White,
    onSurface = Color(0xFF101418),
    outline = Color(0xFFD5DAE2),
    error = Color(0xFFC1123F),
)

private val AppTypography = Typography().run {
    copy(
        displaySmall = displaySmall.copy(fontWeight = FontWeight.SemiBold),
        headlineMedium = headlineMedium.copy(fontWeight = FontWeight.SemiBold),
        headlineSmall = headlineSmall.copy(fontWeight = FontWeight.SemiBold),
        titleLarge = titleLarge.copy(fontWeight = FontWeight.SemiBold, letterSpacing = 0.sp),
        titleMedium = titleMedium.copy(fontWeight = FontWeight.Medium),
        labelSmall = labelSmall.copy(fontWeight = FontWeight.Medium, letterSpacing = 0.6.sp),
        bodySmall = bodySmall.copy(color = FinancialColors.OnSurfaceMuted),
    )
}

/** Monospaced-digit style for any number that appears in a column. */
val NumericTextStyle = TextStyle(
    fontFamily = FontFamily.Default,
    fontFeatureSettings = "tnum",
    fontWeight = FontWeight.Medium,
)

@Composable
fun EquitySignalTheme(
    darkTheme: Boolean = true,
    content: @Composable () -> Unit,
) {
    val useDark = darkTheme || isSystemInDarkTheme()
    CompositionLocalProvider(LocalFinancialColors provides LocalFinancialColors.current) {
        MaterialTheme(
            colorScheme = if (useDark) DarkScheme else LightScheme,
            typography = AppTypography,
            content = content,
        )
    }
}
