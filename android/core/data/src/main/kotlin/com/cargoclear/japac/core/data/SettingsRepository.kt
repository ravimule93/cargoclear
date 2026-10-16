package com.cargoclear.japac.core.data

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/** What the person can choose in Settings. Everything here is a preference of this phone: nothing is sent to the server. */
interface SettingsRepository {
    /**
     * Whether the document viewer blocks screenshots and screen recording (Android's FLAG_SECURE). On by default: customs documents are
     * commercially sensitive (docs/ANDROID_APP_PLAN.md, D7).
     */
    val viewerSecure: Flow<Boolean>

    suspend fun setViewerSecure(secure: Boolean)

    /**
     * Whether a notification tells the person that an analysis they started has finished while the app is in the background. Off until they
     * turn it on, because it needs the system's permission to notify and a connection held open while the app is away.
     */
    val notifyRunFinished: Flow<Boolean>

    suspend fun setNotifyRunFinished(notify: Boolean)
}

class DataStoreSettingsRepository(private val store: DataStore<Preferences>) : SettingsRepository {
    override val viewerSecure: Flow<Boolean> = store.data.map { it[VIEWER_SECURE] ?: true }

    override suspend fun setViewerSecure(secure: Boolean) {
        store.edit { it[VIEWER_SECURE] = secure }
    }

    override val notifyRunFinished: Flow<Boolean> = store.data.map { it[NOTIFY_RUN_FINISHED] ?: false }

    override suspend fun setNotifyRunFinished(notify: Boolean) {
        store.edit { it[NOTIFY_RUN_FINISHED] = notify }
    }

    private companion object {
        val VIEWER_SECURE = booleanPreferencesKey("viewer_secure")
        val NOTIFY_RUN_FINISHED = booleanPreferencesKey("notify_run_finished")
    }
}
