package com.equitysignal.core.network

import com.equitysignal.core.model.AlertStatus
import com.equitysignal.core.model.ScoreCategory
import com.equitysignal.core.network.dto.AlertDto
import com.equitysignal.core.network.dto.SellAlertDto
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MapperTest {

    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true; explicitNulls = false }

    @Test
    fun `alert payload maps to the domain model`() {
        val payload = """
            {
              "id": 412, "alert_uid": "6f0d", "ticker": "NVDA", "company_name": "NVIDIA Corp",
              "status": "ACTIVE", "strategy_version": "momentum_breakout_v1.0.0",
              "buy_ts_utc": "2026-08-07T14:32:10Z", "buy_price": 184.32,
              "opportunity_score": 91.4, "confidence": 78.2, "probability": 0.51,
              "probability_sample_size": 214, "expected_value": 0.66, "reward_risk": 2.25,
              "stop_price": 179.8, "target1_price": 191.1, "target2_price": 197.88,
              "current_price": 191.74, "current_return_pct": 4.02,
              "max_gain_pct": 5.18, "max_drawdown_pct": -0.86,
              "buy_reasons": ["Strong bullish trend"], "risk_factors": ["Earnings in 24 days"],
              "component_scores": {"trend": 94.1, "momentum": 88.0, "relative_strength": 86.7}
            }
        """.trimIndent()

        val alert = json.decodeFromString(AlertDto.serializer(), payload).toModel(now = 1_000L)

        assertEquals("NVDA", alert.ticker)
        assertEquals(AlertStatus.ACTIVE, alert.status)
        assertEquals(184.32, alert.buyPrice, 1e-6)
        assertEquals(4.02, alert.currentReturnPct, 1e-6)
        assertEquals(214, alert.probabilitySampleSize)
        assertEquals(94.1, alert.componentScores.trend, 1e-6)
        assertTrue(alert.isOpen)
        assertEquals(1, alert.buyReasons.size)
        assertTrue(alert.buyTsUtc > 0)
    }

    @Test
    fun `an unknown status does not crash the app`() {
        val alert = json
            .decodeFromString(AlertDto.serializer(), """{"status":"SOMETHING_NEW"}""")
            .toModel()
        assertEquals(AlertStatus.UNKNOWN, alert.status)
    }

    @Test
    fun `unknown json fields are ignored`() {
        val alert = json
            .decodeFromString(AlertDto.serializer(), """{"ticker":"AMD","brand_new_field":42}""")
            .toModel()
        assertEquals("AMD", alert.ticker)
    }

    @Test
    fun `a closed alert carries its sell`() {
        val payload = """
            {
              "ticker": "NVDA", "status": "CLOSED", "buy_price": 184.32,
              "final_return_pct": 7.8, "holding_period_days": 3,
              "sell": {
                "alert_uid": "sell-1", "buy_alert_id": 412, "ticker": "NVDA",
                "sell_price": 198.7, "entry_price": 184.32, "final_return_pct": 7.8,
                "exit_reason": "TRAILING_STOP", "holding_period_days": 3
              }
            }
        """.trimIndent()

        val alert = json.decodeFromString(AlertDto.serializer(), payload).toModel()

        assertNotNull(alert.sell)
        assertEquals("TRAILING_STOP", alert.sell!!.exitReason)
        assertEquals(412L, alert.sell!!.buyAlertId)
        assertEquals(7.8, alert.displayReturnPct, 1e-6)
        assertTrue(alert.isClosed)
    }

    @Test
    fun `a sell always references a buy id`() {
        val sell = json
            .decodeFromString(SellAlertDto.serializer(), """{"buy_alert_id": 99, "ticker": "AMD"}""")
            .toModel()
        assertEquals(99L, sell.buyAlertId)
    }

    @Test
    fun `an unparseable timestamp yields null rather than throwing`() {
        val alert = json
            .decodeFromString(AlertDto.serializer(), """{"closed_ts_utc":"not-a-date"}""")
            .toModel()
        assertNull(alert.closedTsUtc)
    }

    @Test
    fun `score category parses leniently`() {
        assertEquals(ScoreCategory.STRONG_BUY, ScoreCategory.from("STRONG_BUY"))
        assertEquals(ScoreCategory.UNKNOWN, ScoreCategory.from("NOT_A_CATEGORY"))
        assertEquals(ScoreCategory.UNKNOWN, ScoreCategory.from(null))
    }
}
