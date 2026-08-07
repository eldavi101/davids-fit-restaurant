package com.equitysignal.core.database

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverters
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Database(
    entities = [
        CachedAlertEntity::class,
        CachedAlertEventEntity::class,
        AlertReadStatusEntity::class,
        CachedScannerEntity::class,
        CachedPositionEntity::class,
        CachedStockEntity::class,
        CachedSnapshotEntity::class,
        UserSettingEntity::class,
    ],
    version = 1,
    exportSchema = true,
)
@TypeConverters(Converters::class)
abstract class EquitySignalDatabase : RoomDatabase() {
    abstract fun alertDao(): AlertDao
    abstract fun scannerDao(): ScannerDao
    abstract fun positionDao(): PositionDao
    abstract fun stockDao(): StockDao
    abstract fun snapshotDao(): SnapshotDao
    abstract fun userSettingDao(): UserSettingDao

    companion object {
        const val NAME = "equity_signal.db"
    }
}

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {

    @Provides
    @Singleton
    fun provideDatabase(@ApplicationContext context: Context): EquitySignalDatabase =
        Room.databaseBuilder(context, EquitySignalDatabase::class.java, EquitySignalDatabase.NAME)
            // No destructive migration: the cache is rebuildable, but read/archived state
            // is local-only and would be lost, so schema changes must ship a real migration.
            .build()

    @Provides fun provideAlertDao(db: EquitySignalDatabase): AlertDao = db.alertDao()
    @Provides fun provideScannerDao(db: EquitySignalDatabase): ScannerDao = db.scannerDao()
    @Provides fun providePositionDao(db: EquitySignalDatabase): PositionDao = db.positionDao()
    @Provides fun provideStockDao(db: EquitySignalDatabase): StockDao = db.stockDao()
    @Provides fun provideSnapshotDao(db: EquitySignalDatabase): SnapshotDao = db.snapshotDao()
    @Provides fun provideUserSettingDao(db: EquitySignalDatabase): UserSettingDao =
        db.userSettingDao()
}
