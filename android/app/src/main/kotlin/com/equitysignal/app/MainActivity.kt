package com.equitysignal.app

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import com.equitysignal.core.designsystem.EquitySignalTheme
import dagger.hilt.android.AndroidEntryPoint

/**
 * Single activity, `singleTask` so a notification deep link resurfaces the running app
 * rather than stacking a second copy of it.
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    private val notificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* declined is fine */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        setContent {
            EquitySignalTheme {
                LaunchedEffect(Unit) {
                    // Asked once, and a refusal is not fatal: the Alert Center remains the
                    // primary mechanism and notifications are only a convenience on top.
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                        notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                    }
                }
                Scaffold { padding ->
                    EquitySignalApp(modifier = Modifier.padding(padding))
                }
            }
        }
    }
}
