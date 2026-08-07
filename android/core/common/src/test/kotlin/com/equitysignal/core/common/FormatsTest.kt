package com.equitysignal.core.common

import com.equitysignal.core.model.Freshness
import org.junit.Assert.assertEquals
import org.junit.Test

class FormatsTest {

    @Test
    fun `returns always carry an explicit sign`() {
        assertEquals("+4.02%", Formats.percent(4.02))
        assertEquals("-1.50%", Formats.percent(-1.5))
        assertEquals("—", Formats.percent(null))
    }

    @Test
    fun `probability always travels with its sample size`() {
        assertEquals("51% (n=214)", Formats.probability(0.51, 214))
        // Zero samples means the number is a configured prior, and it says so.
        assertEquals("40% (prior only)", Formats.probability(0.40, 0))
        assertEquals("—", Formats.probability(null, 10))
    }

    @Test
    fun `money and compact numbers`() {
        assertEquals("$184.32", Formats.money(184.32))
        assertEquals("+$1,250.00", Formats.signedMoney(1250.0))
        assertEquals("-$40.00", Formats.signedMoney(-40.0))
        assertEquals("4.52T", Formats.compactNumber(4.52e12))
        assertEquals("2.4M", Formats.compactNumber(2.4e6))
    }

    @Test
    fun `freshness degrades with age and offline state`() {
        val now = 1_000_000L
        assertEquals(Freshness.LIVE, FreshnessPolicy.classify(now - 10_000, online = true, now = now))
        assertEquals(Freshness.DELAYED, FreshnessPolicy.classify(now - 120_000, online = true, now = now))
        assertEquals(Freshness.CACHED, FreshnessPolicy.classify(now - 3_600_000, online = true, now = now))
        // Offline is always CACHED regardless of age — never implied to be live.
        assertEquals(Freshness.CACHED, FreshnessPolicy.classify(now, online = false, now = now))
        assertEquals(Freshness.CACHED, FreshnessPolicy.classify(null, online = true, now = now))
    }

    @Test
    fun `deep link round trips through the route helper`() {
        assertEquals("equitysignal://alert/abc-123", Routes.alertDeepLink("abc-123"))
        assertEquals("alert_detail/abc-123", Routes.alertDetail("abc-123"))
    }

    @Test
    fun `iso timestamps parse to epoch millis`() {
        assertEquals(0L, MarketTime.parseIso("1970-01-01T00:00:00Z"))
        assertEquals(null, MarketTime.parseIso("nonsense"))
        assertEquals(null, MarketTime.parseIso(null))
    }
}
