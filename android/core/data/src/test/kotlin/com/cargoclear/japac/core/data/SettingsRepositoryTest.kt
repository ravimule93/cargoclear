package com.cargoclear.japac.core.data

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class SettingsRepositoryTest {
    @get:Rule
    val temp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    @After
    fun tearDown() = scope.cancel()

    private fun repository() = DataStoreSettingsRepository(PreferenceDataStoreFactory.create(scope = scope) { temp.root.resolve("settings.preferences_pb") })

    @Test
    fun `screenshots are blocked in the viewer until the person says otherwise`() = runTest {
        assertTrue(repository().viewerSecure.first())
    }

    @Test
    fun `the choice is kept and can be changed back`() = runTest {
        val settings = repository()
        settings.setViewerSecure(false)
        assertFalse(settings.viewerSecure.first())
        settings.setViewerSecure(true)
        assertTrue(settings.viewerSecure.first())
    }

    @Test
    fun `no notification is sent until the person asks for it`() = runTest {
        val settings = repository()
        assertFalse(settings.notifyRunFinished.first())
        settings.setNotifyRunFinished(true)
        assertTrue(settings.notifyRunFinished.first())
        assertTrue("and it does not touch the other choice", settings.viewerSecure.first())
        settings.setNotifyRunFinished(false)
        assertFalse(settings.notifyRunFinished.first())
    }
}
