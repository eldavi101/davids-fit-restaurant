package com.equitysignal.app

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Radar
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.ShowChart
import androidx.compose.material.icons.outlined.AccountBalance
import androidx.compose.material.icons.outlined.Dashboard
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import androidx.navigation.navDeepLink
import com.equitysignal.core.common.Routes
import com.equitysignal.feature.alerts.AlertDetailScreen
import com.equitysignal.feature.alerts.AlertsScreen
import com.equitysignal.feature.analytics.AnalyticsScreen
import com.equitysignal.feature.backtesting.BacktestingScreen
import com.equitysignal.feature.dashboard.DashboardScreen
import com.equitysignal.feature.history.HistoryScreen
import com.equitysignal.feature.positions.PositionsScreen
import com.equitysignal.feature.scanner.ScannerScreen
import com.equitysignal.feature.settings.SettingsScreen
import com.equitysignal.feature.settings.SystemStatusScreen
import com.equitysignal.feature.stockdetails.StockDetailScreen

private data class BottomDestination(
    val route: String,
    val label: String,
    val icon: ImageVector,
)

private val bottomDestinations = listOf(
    BottomDestination(Routes.HOME, "Home", Icons.Outlined.Dashboard),
    BottomDestination(Routes.SCANNER, "Scanner", Icons.Filled.Radar),
    BottomDestination(Routes.ALERTS, "Alerts", Icons.Filled.Notifications),
    BottomDestination(Routes.POSITIONS, "Positions", Icons.Outlined.AccountBalance),
    BottomDestination(Routes.ANALYTICS, "Analytics", Icons.Filled.Insights),
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EquitySignalApp(
    modifier: Modifier = Modifier,
    navController: NavHostController = rememberNavController(),
    badgeViewModel: UnreadBadgeViewModel = hiltViewModel(),
) {
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentDestination = backStackEntry?.destination
    val unreadCount by badgeViewModel.unreadCount.collectAsStateWithLifecycle()

    Scaffold(
        modifier = modifier.fillMaxSize(),
        topBar = {
            TopAppBar(
                title = { Text(titleFor(currentDestination?.route)) },
                actions = {
                    IconButton(onClick = { navController.navigate(Routes.HISTORY) }) {
                        Icon(Icons.Filled.ShowChart, contentDescription = "Trade history")
                    }
                    IconButton(onClick = { navController.navigate(Routes.SETTINGS) }) {
                        Icon(Icons.Filled.Settings, contentDescription = "Settings")
                    }
                },
            )
        },
        bottomBar = {
            NavigationBar {
                bottomDestinations.forEach { destination ->
                    val selected = currentDestination?.hierarchy?.any { it.route == destination.route } == true
                    NavigationBarItem(
                        selected = selected,
                        onClick = {
                            navController.navigate(destination.route) {
                                popUpTo(navController.graph.findStartDestination().id) { saveState = true }
                                launchSingleTop = true
                                restoreState = true
                            }
                        },
                        icon = {
                            // "Alerts 🔔 3" — the unread badge required by requirement 5.
                            if (destination.route == Routes.ALERTS && unreadCount > 0) {
                                BadgedBox(badge = { Badge { Text(unreadCount.coerceAtMost(99).toString()) } }) {
                                    Icon(destination.icon, contentDescription = destination.label)
                                }
                            } else {
                                Icon(destination.icon, contentDescription = destination.label)
                            }
                        },
                        label = { Text(destination.label) },
                    )
                }
            }
        },
    ) { padding ->
        Box(Modifier.padding(padding)) {
            EquitySignalNavHost(navController)
        }
    }
}

@Composable
private fun EquitySignalNavHost(navController: NavHostController) {
    NavHost(navController = navController, startDestination = Routes.HOME) {

        composable(Routes.HOME) {
            DashboardScreen(
                onOpportunityClick = { navController.navigate(Routes.stockDetail(it)) },
                onAlertClick = { navController.navigate(Routes.alertDetail(it)) },
            )
        }

        composable(Routes.SCANNER) {
            ScannerScreen(onStockClick = { navController.navigate(Routes.stockDetail(it)) })
        }

        composable(Routes.ALERTS) {
            AlertsScreen(onAlertClick = { navController.navigate(Routes.alertDetail(it)) })
        }

        composable(Routes.POSITIONS) { PositionsScreen() }
        composable(Routes.ANALYTICS) { AnalyticsScreen() }

        composable(Routes.HISTORY) {
            HistoryScreen(onTradeClick = { navController.navigate(Routes.alertDetail(it)) })
        }

        composable(Routes.BACKTESTING) { BacktestingScreen() }
        composable(Routes.SETTINGS) { SettingsScreen() }
        composable(Routes.SYSTEM_STATUS) { SystemStatusScreen() }

        /**
         * Alert detail, reachable both in-app and from a local notification.
         *
         * The deep link is what makes requirement 60.20 true: tapping a notification opens
         * the exact alert it refers to, not a list.
         */
        composable(
            route = Routes.ALERT_DETAIL,
            arguments = listOf(navArgument("alertUid") { type = NavType.StringType }),
            deepLinks = listOf(navDeepLink { uriPattern = Routes.ALERT_DEEP_LINK }),
        ) { entry ->
            val alertUid = entry.arguments?.getString("alertUid").orEmpty()
            AlertDetailScreen(
                alertUid = alertUid,
                onStockClick = { navController.navigate(Routes.stockDetail(it)) },
                onBack = { navController.popBackStack() },
            )
        }

        composable(
            route = Routes.STOCK_DETAIL,
            arguments = listOf(navArgument("ticker") { type = NavType.StringType }),
        ) { entry ->
            StockDetailScreen(
                ticker = entry.arguments?.getString("ticker").orEmpty(),
                onAlertClick = { navController.navigate(Routes.alertDetail(it)) },
            )
        }
    }
}

private fun titleFor(route: String?): String = when {
    route == null -> "Equity Signal"
    route.startsWith("alert_detail") -> "Alert"
    route.startsWith("stock_detail") -> "Stock"
    route == Routes.HOME -> "Equity Signal"
    route == Routes.SCANNER -> "Scanner"
    route == Routes.ALERTS -> "Alert Center"
    route == Routes.POSITIONS -> "Paper Portfolio"
    route == Routes.ANALYTICS -> "Analytics"
    route == Routes.HISTORY -> "History"
    route == Routes.BACKTESTING -> "Backtesting"
    route == Routes.SETTINGS -> "Settings"
    route == Routes.SYSTEM_STATUS -> "System Status"
    else -> "Equity Signal"
}
