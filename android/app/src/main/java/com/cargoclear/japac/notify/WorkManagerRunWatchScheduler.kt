package com.cargoclear.japac.notify

import android.content.Context
import androidx.work.Constraints
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.WorkManager
import com.cargoclear.japac.core.model.WatchedRun
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class WorkManagerRunWatchScheduler @Inject constructor(@ApplicationContext private val context: Context) : RunWatchScheduler {
    private val workManager: WorkManager get() = WorkManager.getInstance(context)

    override fun watch(run: WatchedRun) {
        val request = OneTimeWorkRequestBuilder<RunWatchWorker>()
            .setInputData(Data.Builder().putString(RunWatchWorker.KEY_BUNDLE, run.bundleId).putString(RunWatchWorker.KEY_RUN, run.runId).build())
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            // expedited so it starts while the app is away; if the system has no quota left it still runs, as ordinary work, a little later
            .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
            .addTag(TAG)
            .build()
        workManager.enqueueUniqueWork("$TAG-${run.bundleId}", ExistingWorkPolicy.REPLACE, request)
    }

    override fun cancelAll() {
        workManager.cancelAllWorkByTag(TAG)
    }

    private companion object {
        const val TAG = "run-watch"
    }
}
