package com.equitysignal.data.di

import android.content.Context
import androidx.work.WorkManager
import com.equitysignal.core.common.DefaultDispatcher
import com.equitysignal.core.common.IoDispatcher
import com.equitysignal.core.datastore.AppPreferences
import com.equitysignal.core.network.ApiKeyInterceptor
import com.equitysignal.core.network.BaseUrlInterceptor
import com.equitysignal.data.AlertRepositoryImpl
import com.equitysignal.data.BacktestRepositoryImpl
import com.equitysignal.data.MarketRepositoryImpl
import com.equitysignal.data.PortfolioRepositoryImpl
import com.equitysignal.data.ScannerRepositoryImpl
import com.equitysignal.data.SettingsRepositoryImpl
import com.equitysignal.data.StockRepositoryImpl
import com.equitysignal.data.SyncRepositoryImpl
import com.equitysignal.domain.AlertRepository
import com.equitysignal.domain.BacktestRepository
import com.equitysignal.domain.MarketRepository
import com.equitysignal.domain.PortfolioRepository
import com.equitysignal.domain.ScannerRepository
import com.equitysignal.domain.SettingsRepository
import com.equitysignal.domain.StockRepository
import com.equitysignal.domain.SyncRepository
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking

/** Binds the domain's repository interfaces to their data-layer implementations. */
@Module
@InstallIn(SingletonComponent::class)
abstract class RepositoryModule {

    @Binds @Singleton
    abstract fun bindAlertRepository(impl: AlertRepositoryImpl): AlertRepository

    @Binds @Singleton
    abstract fun bindScannerRepository(impl: ScannerRepositoryImpl): ScannerRepository

    @Binds @Singleton
    abstract fun bindMarketRepository(impl: MarketRepositoryImpl): MarketRepository

    @Binds @Singleton
    abstract fun bindPortfolioRepository(impl: PortfolioRepositoryImpl): PortfolioRepository

    @Binds @Singleton
    abstract fun bindStockRepository(impl: StockRepositoryImpl): StockRepository

    @Binds @Singleton
    abstract fun bindBacktestRepository(impl: BacktestRepositoryImpl): BacktestRepository

    @Binds @Singleton
    abstract fun bindSettingsRepository(impl: SettingsRepositoryImpl): SettingsRepository

    @Binds @Singleton
    abstract fun bindSyncRepository(impl: SyncRepositoryImpl): SyncRepository
}

@Module
@InstallIn(SingletonComponent::class)
object DispatcherModule {
    @Provides @IoDispatcher
    fun provideIoDispatcher(): CoroutineDispatcher = Dispatchers.IO

    @Provides @DefaultDispatcher
    fun provideDefaultDispatcher(): CoroutineDispatcher = Dispatchers.Default
}

@Module
@InstallIn(SingletonComponent::class)
object AppInfraModule {

    @Provides
    @Singleton
    fun provideWorkManager(@ApplicationContext context: Context): WorkManager =
        WorkManager.getInstance(context)

    /**
     * The interceptors read the current connection settings on every call.
     *
     * `runBlocking` here is intentional and bounded: OkHttp interceptors are synchronous by
     * contract, and this reads a DataStore value that is already in memory. Rebuilding the
     * whole Retrofit stack whenever the user edits the URL would be far worse.
     */
    @Provides
    @Singleton
    fun provideApiKeyInterceptor(preferences: AppPreferences): ApiKeyInterceptor =
        ApiKeyInterceptor { runBlocking { preferences.current().apiKey } }

    @Provides
    @Singleton
    fun provideBaseUrlInterceptor(preferences: AppPreferences): BaseUrlInterceptor =
        BaseUrlInterceptor { runBlocking { preferences.current().baseUrl } }
}
