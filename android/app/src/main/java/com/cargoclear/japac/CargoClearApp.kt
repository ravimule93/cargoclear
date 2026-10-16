package com.cargoclear.japac

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import com.cargoclear.japac.notify.RunNotifier
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject

/** WorkManager is started on first use with Hilt's worker factory (the default initializer is removed in the manifest), so workers get their dependencies. */
@HiltAndroidApp
class CargoClearApp : Application(), Configuration.Provider {
    @Inject lateinit var workerFactory: HiltWorkerFactory

    @Inject lateinit var notifier: RunNotifier

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder().setWorkerFactory(workerFactory).build()

    override fun onCreate() {
        super.onCreate()
        notifier.createChannels()
    }
}
