package com.equitysignal.feature.alerts

import app.cash.turbine.test
import com.equitysignal.core.model.Alert
import com.equitysignal.core.model.AlertEvent
import com.equitysignal.core.model.AlertStatus
import com.equitysignal.core.model.ComponentScores
import com.equitysignal.core.model.SellAlert
import com.equitysignal.domain.AlertRepository
import com.equitysignal.domain.AlertsTab
import com.equitysignal.domain.ArchiveAlertUseCase
import com.equitysignal.domain.ObserveAlertsUseCase
import com.equitysignal.domain.ObserveUnreadAlertCountUseCase
import com.equitysignal.domain.RefreshAlertsUseCase
import com.equitysignal.domain.SyncNowUseCase
import com.equitysignal.domain.SyncOutcome
import com.equitysignal.domain.SyncRepository
import com.equitysignal.core.model.DashboardSummary
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class AlertsViewModelTest {

    private val dispatcher = StandardTestDispatcher()
    private lateinit var repository: FakeAlertRepository

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
        repository = FakeAlertRepository()
    }

    @After
    fun tearDown() = Dispatchers.resetMain()

    private fun viewModel(sync: SyncRepository = FakeSyncRepository()) = AlertsViewModel(
        observeAlerts = ObserveAlertsUseCase(repository),
        observeUnreadCount = ObserveUnreadAlertCountUseCase(repository),
        refreshAlerts = RefreshAlertsUseCase(repository),
        archiveAlert = ArchiveAlertUseCase(repository),
        syncNow = SyncNowUseCase(sync),
    )

    @Test
    fun `starts loading then emits the cached alerts`() = runTest(dispatcher) {
        repository.alerts.value = listOf(alert("a"), alert("b"))

        viewModel().uiState.test {
            assertEquals(AlertsUiState.Loading, awaitItem())
            val ready = awaitItem() as AlertsUiState.Ready
            assertEquals(2, ready.alerts.size)
            assertEquals(AlertsTab.ALL, ready.tab)
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `switching to the closed tab shows only closed trades`() = runTest(dispatcher) {
        repository.alerts.value = listOf(
            alert("open", AlertStatus.ACTIVE),
            alert("done", AlertStatus.CLOSED),
        )
        val model = viewModel()

        model.uiState.test {
            awaitItem() // Loading
            assertEquals(2, (awaitItem() as AlertsUiState.Ready).alerts.size)

            model.selectTab(AlertsTab.CLOSED)
            val closed = awaitItem() as AlertsUiState.Ready
            assertEquals(AlertsTab.CLOSED, closed.tab)
            assertEquals(listOf("done"), closed.alerts.map { it.alertUid })
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `a refresh failure keeps the cached alerts visible`() = runTest(dispatcher) {
        // The point of the Error-with-cache shape: an offline user still sees their alerts.
        repository.alerts.value = listOf(alert("a"))
        repository.refreshResult = Result.failure(IllegalStateException("network down"))

        val model = viewModel()
        model.uiState.test {
            awaitItem() // Loading
            var latest = awaitItem() as AlertsUiState.Ready
            while (latest.error == null) latest = awaitItem() as AlertsUiState.Ready

            assertEquals("network down", latest.error)
            assertEquals(1, latest.alerts.size)
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `unread count is surfaced for the badge`() = runTest(dispatcher) {
        repository.alerts.value = listOf(alert("a"), alert("b", isRead = false), alert("c", isRead = true))

        viewModel().uiState.test {
            awaitItem()
            val ready = awaitItem() as AlertsUiState.Ready
            assertEquals(2, ready.unreadCount)
            cancelAndIgnoreRemainingEvents()
        }
    }

    @Test
    fun `archiving delegates to the repository and never deletes`() = runTest(dispatcher) {
        repository.alerts.value = listOf(alert("a"))
        val model = viewModel()

        model.archive("a", archived = true)
        dispatcher.scheduler.advanceUntilIdle()

        assertEquals("a" to true, repository.archived)
        assertTrue(repository.deleted.isEmpty())
    }
}

private fun alert(
    uid: String,
    status: AlertStatus = AlertStatus.ACTIVE,
    isRead: Boolean = false,
) = Alert(
    id = uid.hashCode().toLong(),
    alertUid = uid,
    ticker = "TEST",
    companyName = "Test Co",
    status = status,
    strategyVersion = "momentum_breakout_v1.0.0",
    buyTsUtc = 1_000L,
    buyPrice = 100.0,
    opportunityScore = 88.0,
    confidence = 70.0,
    probability = 0.5,
    probabilitySampleSize = 120,
    expectedValue = 0.4,
    rewardRisk = 2.25,
    marketRegime = "BULL",
    sector = "Technology",
    industry = null,
    breakoutType = null,
    stopPrice = 95.0,
    currentStopPrice = 95.0,
    trailingStopPrice = null,
    target1Price = 107.5,
    target2Price = 115.0,
    currentPrice = 104.0,
    currentReturnPct = 4.0,
    maxGainPct = 5.0,
    maxDrawdownPct = -1.0,
    remainingFraction = 1.0,
    thesisValid = true,
    thesisNotes = emptyList(),
    buyReasons = listOf("Strong trend"),
    riskFactors = emptyList(),
    componentScores = ComponentScores(trend = 90.0),
    closedTsUtc = if (status == AlertStatus.CLOSED) 2_000L else null,
    finalReturnPct = if (status == AlertStatus.CLOSED) 7.8 else null,
    holdingPeriodDays = if (status == AlertStatus.CLOSED) 3 else null,
    sell = if (status == AlertStatus.CLOSED) {
        SellAlert(
            alertUid = "$uid-sell", buyAlertId = uid.hashCode().toLong(), ticker = "TEST",
            sellTsUtc = 2_000L, sellPrice = 107.8, entryPrice = 100.0, fractionClosed = 1.0,
            finalReturnPct = 7.8, rMultiple = 1.56, holdingPeriodDays = 3,
            exitReason = "TRAILING_STOP", exitReasonDetail = null,
            maxGainPct = 9.0, maxDrawdownPct = -1.0, strategyVersion = "momentum_breakout_v1.0.0",
        )
    } else null,
    fetchedAtUtc = 3_000L,
    isRead = isRead,
)

private class FakeAlertRepository : AlertRepository {
    val alerts = MutableStateFlow<List<Alert>>(emptyList())
    var refreshResult: Result<Unit> = Result.success(Unit)
    var archived: Pair<String, Boolean>? = null
    val deleted = mutableListOf<String>()

    override fun observeAll(): Flow<List<Alert>> = alerts
    override fun observeActive(): Flow<List<Alert>> = alerts.map { list -> list.filter { it.isOpen } }
    override fun observeClosed(): Flow<List<Alert>> = alerts.map { list -> list.filter { it.isClosed } }
    override fun observeSells(): Flow<List<Alert>> = alerts.map { list -> list.filter { it.sell != null } }
    override fun observeAlert(alertUid: String): Flow<Alert?> =
        alerts.map { list -> list.firstOrNull { it.alertUid == alertUid } }
    override fun observeTimeline(alertUid: String): Flow<List<AlertEvent>> = emptyFlow()
    override fun observeUnreadCount(): Flow<Int> =
        alerts.map { list -> list.count { !it.isRead && !it.isArchived } }
    override fun observeForTicker(ticker: String): Flow<List<Alert>> = alerts

    override suspend fun refresh(): Result<Unit> = refreshResult
    override suspend fun refreshTimeline(alertUid: String): Result<Unit> = Result.success(Unit)
    override suspend fun markRead(alertUid: String) {
        alerts.value = alerts.value.map { if (it.alertUid == alertUid) it.copy(isRead = true) else it }
    }
    override suspend fun setArchived(alertUid: String, archived: Boolean) {
        this.archived = alertUid to archived
    }
}

private class FakeSyncRepository : SyncRepository {
    override suspend fun sync(): SyncOutcome = SyncOutcome.Success(0, 0, 0L)
    override fun observeDashboard(): Flow<DashboardSummary> = emptyFlow()
}
