package com.cargoclear.japac.ui.shell

import app.cash.turbine.test
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.data.MetaRepository
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.ErrorEnvelope
import com.cargoclear.japac.core.model.Meta
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class MetaViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() = Dispatchers.setMain(dispatcher)

    @After
    fun tearDown() = Dispatchers.resetMain()

    private class FakeRepository(private val answers: ArrayDeque<() -> Meta>) : MetaRepository {
        val forced = mutableListOf<Boolean>()

        override suspend fun load(forceRefresh: Boolean): Meta {
            forced += forceRefresh
            return answers.removeFirst()()
        }
    }

    private fun failure(kind: ApiException.Kind, message: String): () -> Meta = {
        throw ApiException(ErrorEnvelope(code = "X", message = message), kind)
    }

    private val demo = Meta(AppMode.DEMO, "fixtures")

    @Test
    fun `loads the mode and shows it`() = runTest(dispatcher) {
        val viewModel = MetaViewModel(FakeRepository(ArrayDeque(listOf({ demo }))))

        viewModel.state.test {
            assertEquals(MetaState.Loading, awaitItem())
            advanceUntilIdle()
            assertEquals(MetaState.Ready(demo), awaitItem())
        }
    }

    @Test
    fun `a failure is shown and retry asks the repository to refetch`() = runTest(dispatcher) {
        val repository = FakeRepository(ArrayDeque(listOf(failure(ApiException.Kind.NETWORK, "down"), { demo })))
        val viewModel = MetaViewModel(repository)

        advanceUntilIdle()
        assertEquals(MetaState.Failed("down", notConfigured = false), viewModel.state.value)

        viewModel.retry()
        assertEquals(MetaState.Loading, viewModel.state.value)
        advanceUntilIdle()

        assertEquals(MetaState.Ready(demo), viewModel.state.value)
        assertEquals(listOf(false, true), repository.forced)
    }

    @Test
    fun `a build without a backend address is told apart from an unreachable one`() = runTest(dispatcher) {
        val viewModel = MetaViewModel(FakeRepository(ArrayDeque(listOf(failure(ApiException.Kind.NOT_CONFIGURED, "none")))))

        advanceUntilIdle()

        val state = viewModel.state.value
        assertTrue(state is MetaState.Failed && state.notConfigured)
    }
}
