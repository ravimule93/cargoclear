package com.cargoclear.japac.notify

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.ForegroundInfo
import com.cargoclear.japac.MainActivity
import com.cargoclear.japac.R
import com.cargoclear.japac.core.model.Status
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The two kinds of notification the app posts: a short-lived "waiting for the analysis" while the watcher holds the stream, and the result.
 * Nothing about a bundle shows on a locked screen: the lock screen gets a version that only says an analysis finished.
 */
@Singleton
class RunNotifier @Inject constructor(@ApplicationContext private val context: Context) : NotificationsEnabled {
    private val manager get() = NotificationManagerCompat.from(context)

    /** Channels exist from the app's start so the person can see and change them in the system settings before the first notification. */
    fun createChannels() {
        if (Build.VERSION.SDK_INT < 26) return
        val system = context.getSystemService(NotificationManager::class.java)
        system.createNotificationChannel(
            NotificationChannel(CHANNEL_RESULT, context.getString(R.string.notify_channel_result_name), NotificationManager.IMPORTANCE_DEFAULT)
                .apply { description = context.getString(R.string.notify_channel_result_description) },
        )
        system.createNotificationChannel(
            NotificationChannel(CHANNEL_WATCH, context.getString(R.string.notify_channel_watch_name), NotificationManager.IMPORTANCE_LOW)
                .apply { description = context.getString(R.string.notify_channel_watch_description) },
        )
    }

    override fun check(): Boolean {
        val permitted = Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        return permitted && manager.areNotificationsEnabled()
    }

    /** What the system shows while the watcher runs as a foreground service (it must show something, and says what it is doing). */
    fun foregroundInfo(bundleId: String): ForegroundInfo {
        val notification = NotificationCompat.Builder(context, CHANNEL_WATCH)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(context.getString(R.string.notify_watch_title))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .build()
        val id = idOf(bundleId, WATCH)
        return if (Build.VERSION.SDK_INT >= 29) ForegroundInfo(id, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC) else ForegroundInfo(id, notification)
    }

    /** "Analysis finished: <bundle>: <verdict>"; the verdict is left out when it is not one this app knows. Tapping opens the bundle. */
    fun finished(bundleId: String, bundleTitle: String, status: Status?) {
        val verdict = status?.let { context.getString(statusText(it)) }
        val text = if (verdict != null) context.getString(R.string.notify_finished_text, bundleTitle, verdict) else bundleTitle
        post(bundleId, context.getString(R.string.notify_finished_title), text, context.getString(R.string.notify_finished_public))
    }

    fun failed(bundleId: String, bundleTitle: String, message: String?) {
        val text = listOfNotNull(bundleTitle, message?.takeIf { it.isNotBlank() }).joinToString(": ")
        post(bundleId, context.getString(R.string.notify_failed_title), text, context.getString(R.string.notify_failed_public))
    }

    private fun post(bundleId: String, title: String, text: String, publicText: String) {
        if (!check()) return
        val open = PendingIntent.getActivity(
            context,
            idOf(bundleId, RESULT),
            Intent(context, MainActivity::class.java).putExtra(MainActivity.EXTRA_BUNDLE_ID, bundleId).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val publicVersion = NotificationCompat.Builder(context, CHANNEL_RESULT).setSmallIcon(R.drawable.ic_notification).setContentTitle(publicText).build()
        val notification: Notification = NotificationCompat.Builder(context, CHANNEL_RESULT)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setAutoCancel(true)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setPublicVersion(publicVersion)
            .build()
        @Suppress("MissingPermission") // check() above is the permission check
        manager.notify(idOf(bundleId, RESULT), notification)
    }

    private fun statusText(status: Status): Int = when (status) {
        Status.COMPLIANT_FOR_SUBMISSION -> R.string.status_compliant
        Status.MISSING_EVIDENCE -> R.string.status_missing_evidence
        Status.MATERIAL_CONTRADICTION -> R.string.status_material_contradiction
        Status.SPECIALIST_REVIEW_REQUIRED -> R.string.status_specialist_review
    }

    /** One id per bundle and kind, so a second result for the same bundle replaces the first instead of piling up. */
    private fun idOf(bundleId: String, kind: Int): Int = (bundleId.hashCode() and 0x3FFFFFFF) * 4 + kind

    companion object {
        const val CHANNEL_RESULT = "analysis_result"
        const val CHANNEL_WATCH = "analysis_watch"
        private const val RESULT = 1
        private const val WATCH = 2
    }
}
