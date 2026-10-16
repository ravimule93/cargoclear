package com.cargoclear.japac.ui.settings

import com.cargoclear.japac.ui.FakeDocumentFiles
import com.cargoclear.japac.ui.FakePrefillFiles
import com.cargoclear.japac.ui.FakeSettings
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class SettingsViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val settings = FakeSettings(secure = true)
    private val files = FakeDocumentFiles().apply { size = 3_500_000 }
    private val prefill = FakePrefillFiles().apply { size = 500_000 }

    @Before
    fun setUp() = Dispatchers.setMain(dispatcher)

    @After
    fun tearDown() = Dispatchers.resetMain()

    @Test
    fun `the screen starts with screenshots blocked and shows what the downloaded documents take`() = runTest(dispatcher) {
        val vm = SettingsViewModel(settings, files, prefill)
        runCurrent()
        assertTrue(vm.viewerSecure.value)
        assertEquals("documents and pre-fill packs together", 4_000_000L, vm.cacheBytes.value)
    }

    @Test
    fun `the choice about screenshots is kept`() = runTest(dispatcher) {
        val vm = SettingsViewModel(settings, files, prefill)
        runCurrent()
        vm.setViewerSecure(false)
        runCurrent()
        assertFalse(vm.viewerSecure.value)
        vm.setViewerSecure(true)
        runCurrent()
        assertTrue(vm.viewerSecure.value)
    }

    @Test
    fun `clearing the downloaded documents empties the cache and the size shown`() = runTest(dispatcher) {
        val vm = SettingsViewModel(settings, files, prefill)
        runCurrent()
        vm.clearCache()
        runCurrent()
        assertTrue(files.cleared)
        assertTrue("the pre-fill packs that were shared are removed too", prefill.cleared)
        assertEquals(0L, vm.cacheBytes.value)
    }
}
