package com.equitysignal.core.database

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class AlertDaoTest {

    private lateinit var db: EquitySignalDatabase
    private lateinit var dao: AlertDao

    @Before
    fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            EquitySignalDatabase::class.java,
        ).allowMainThreadQueries().build()
        dao = db.alertDao()
    }

    @After
    fun tearDown() = db.close()

    private fun alert(uid: String, status: String = "ACTIVE", price: Double = 100.0) =
        CachedAlertEntity(
            alertUid = uid, id = uid.hashCode().toLong(), ticker = "TEST", companyName = "Test Co",
            status = status, strategyVersion = "v1", buyTsUtc = 1_000L, buyPrice = price,
            opportunityScore = 88.0, confidence = 70.0, probability = 0.5,
            probabilitySampleSize = 100, expectedValue = 0.4, rewardRisk = 2.25,
            marketRegime = "BULL", sector = "Technology", industry = null, breakoutType = null,
            stopPrice = 95.0, currentStopPrice = 95.0, trailingStopPrice = null,
            target1Price = 107.5, target2Price = 115.0, currentPrice = price,
            currentReturnPct = 0.0, maxGainPct = 0.0, maxDrawdownPct = 0.0,
            remainingFraction = 1.0, thesisValid = true, thesisNotes = emptyList(),
            buyReasons = listOf("Strong trend"), riskFactors = emptyList(),
            trendScore = 90.0, momentumScore = 80.0, volumeScore = 70.0, breakoutScore = 85.0,
            relativeStrengthScore = 75.0, fundamentalScore = 50.0, riskScore = 65.0,
            closedTsUtc = null, finalReturnPct = null, holdingPeriodDays = null,
            sellUid = null, sellTsUtc = null, sellPrice = null, sellReason = null,
            sellReasonDetail = null, sellRMultiple = null, fetchedAtUtc = 2_000L,
        )

    @Test
    fun `read status survives an alert refresh`() = runTest {
        dao.upsert(listOf(alert("uid-1")))
        dao.markRead("uid-1", now = 5_000L)
        assertEquals(0, dao.observeUnreadCount().first())

        // A sync writes the alert again with a new price. The user already read it, and
        // that must not be undone — this is the whole reason read state lives in its own
        // table (docs/DATABASE_SCHEMA.md, Room cache section).
        dao.upsert(listOf(alert("uid-1", price = 120.0)))

        val row = dao.getOne("uid-1")
        assertEquals(120.0, row!!.buyPrice, 1e-9)
        assertTrue(row.isRead == true)
        assertEquals(0, dao.observeUnreadCount().first())
    }

    @Test
    fun `unread count ignores archived alerts`() = runTest {
        dao.upsert(listOf(alert("a"), alert("b"), alert("c")))
        assertEquals(3, dao.observeUnreadCount().first())

        dao.markArchived("b", archived = true)
        assertEquals(2, dao.observeUnreadCount().first())

        dao.markRead("a", now = 1L)
        assertEquals(1, dao.observeUnreadCount().first())
    }

    @Test
    fun `archiving hides an alert but never deletes it`() = runTest {
        dao.upsert(listOf(alert("uid-1")))
        dao.markArchived("uid-1", archived = true)

        val row = dao.getOne("uid-1")
        assertTrue(row != null)
        assertTrue(row!!.isArchived == true)
    }

    @Test
    fun `active and closed queries partition by status`() = runTest {
        dao.upsert(listOf(alert("open", status = "ACTIVE"), alert("done", status = "CLOSED")))

        assertEquals(listOf("open"), dao.observeActive().first().map { it.alertUid })
        assertEquals(listOf("done"), dao.observeClosed().first().map { it.alertUid })
        assertEquals(2, dao.observeAll().first().size)
    }

    @Test
    fun `notified flag prevents a duplicate notification after a re-sync`() = runTest {
        dao.upsert(listOf(alert("uid-1")))
        assertFalse("uid-1" in dao.notifiedUids())

        dao.markNotified("uid-1")
        assertTrue("uid-1" in dao.notifiedUids())

        dao.upsert(listOf(alert("uid-1", price = 130.0)))
        assertTrue("uid-1" in dao.notifiedUids())
    }

    @Test
    fun `timeline events are stored in order`() = runTest {
        dao.upsert(listOf(alert("uid-1")))
        dao.upsertEvents(
            listOf(
                CachedAlertEventEntity("uid-1", 3_000L, "SELL_SIGNAL", 110.0, "SELL SIGNAL", null),
                CachedAlertEventEntity("uid-1", 1_000L, "BUY_SIGNAL", 100.0, "BUY SIGNAL", null),
            )
        )
        val events = dao.observeTimeline("uid-1").first()
        assertEquals(listOf("BUY_SIGNAL", "SELL_SIGNAL"), events.map { it.eventType })
    }
}
