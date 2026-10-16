package com.cargoclear.japac.core.data

import android.content.Context
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.preferencesDataStoreFile
import androidx.room.Room
import com.cargoclear.japac.core.data.local.CargoClearDatabase
import com.cargoclear.japac.core.data.local.RecentBundlesDao
import com.cargoclear.japac.core.data.work.BatchFiles
import com.cargoclear.japac.core.data.work.UploadScheduler
import com.cargoclear.japac.core.data.work.WorkManagerUploadScheduler
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import java.io.File
import java.util.concurrent.TimeUnit
import javax.inject.Singleton
import okhttp3.OkHttpClient

/** [ApiConfig] is provided by the app module (it owns BuildConfig). */
@Module
@InstallIn(SingletonComponent::class)
internal object NetworkModule {
    @Provides
    @Singleton
    fun okHttpClient(): OkHttpClient = OkHttpClient.Builder()
        .addInterceptor(RequestIdInterceptor())
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    @Provides
    @Singleton
    fun backend(config: ApiConfig, client: OkHttpClient): Backend = Backend(config, client)

    @Provides
    @Singleton
    fun documentFiles(@ApplicationContext context: Context, backend: Backend): DocumentFiles =
        CachedDocumentFiles(File(context.cacheDir, "documents"), backend)

    @Provides
    @Singleton
    fun prefillFiles(@ApplicationContext context: Context, backend: Backend): PrefillFiles =
        CachedPrefillFiles(File(context.cacheDir, "prefill"), backend)

    @Provides
    @Singleton
    fun batchFiles(@ApplicationContext context: Context): BatchFiles = BatchFiles.forContext(context)

    @Provides
    @Singleton
    fun bundleStreamClient(@ApplicationContext context: Context, config: ApiConfig, client: OkHttpClient): BundleStreamClient =
        BundleStreamClient(config, client, reconnectSignals = context.networkBecameAvailable())
}

@Module
@InstallIn(SingletonComponent::class)
internal object SettingsModule {
    @Provides
    @Singleton
    fun settings(@ApplicationContext context: Context): SettingsRepository =
        DataStoreSettingsRepository(PreferenceDataStoreFactory.create { context.preferencesDataStoreFile("settings") })
}

@Module
@InstallIn(SingletonComponent::class)
internal object DatabaseModule {
    /** No destructive fallback: the rows are the only way back to a bundle (no list endpoint, no accounts), so a schema change needs a migration. */
    @Provides
    @Singleton
    fun database(@ApplicationContext context: Context): CargoClearDatabase =
        Room.databaseBuilder(context, CargoClearDatabase::class.java, "cargoclear.db").build()

    @Provides
    fun recentBundlesDao(database: CargoClearDatabase): RecentBundlesDao = database.recentBundles()
}

@Module
@InstallIn(SingletonComponent::class)
internal abstract class RepositoryModule {
    @Binds
    abstract fun metaRepository(impl: NetworkMetaRepository): MetaRepository

    @Binds
    abstract fun bundleRepository(impl: NetworkBundleRepository): BundleRepository

    @Binds
    abstract fun recentBundlesRepository(impl: RoomRecentBundlesRepository): RecentBundlesRepository

    @Binds
    abstract fun documentRepository(impl: NetworkDocumentRepository): DocumentRepository

    @Binds
    abstract fun correctionRepository(impl: NetworkCorrectionRepository): CorrectionRepository

    @Binds
    abstract fun auditRepository(impl: NetworkAuditRepository): AuditRepository

    @Binds
    abstract fun fileImporter(impl: ContextFileImporter): FileImporter

    @Binds
    abstract fun uploadScheduler(impl: WorkManagerUploadScheduler): UploadScheduler
}
