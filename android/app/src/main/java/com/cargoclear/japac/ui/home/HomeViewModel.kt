package com.cargoclear.japac.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.data.BundleRepository
import com.cargoclear.japac.core.data.DemoCase
import com.cargoclear.japac.core.data.RecentBundle
import com.cargoclear.japac.core.data.RecentBundlesRepository
import com.cargoclear.japac.core.model.Bundle
import com.cargoclear.japac.core.model.Destination
import com.cargoclear.japac.core.model.extractBundleId
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** What the home screen is busy with (the web's `Pending`). */
enum class Pending { EMPTY, DEMO_C, DEMO_D }

data class HomeUiState(
    val destination: Destination = Destination.SINGAPORE,
    val pending: Pending? = null,
    val error: String? = null,
    /** The text typed into "open a bundle" is neither an id nor a bundle link. */
    val openInvalid: Boolean = false,
    val recents: List<RecentBundle> = emptyList(),
)

/** The start screen (port of app/page.tsx): create a bundle, open one by id or link, and the bundles this phone has seen. */
@HiltViewModel
class HomeViewModel @Inject constructor(
    private val bundles: BundleRepository,
    private val recents: RecentBundlesRepository,
) : ViewModel() {
    private data class Local(
        val destination: Destination = Destination.SINGAPORE,
        val pending: Pending? = null,
        val error: String? = null,
        val openInvalid: Boolean = false,
    )

    private val local = MutableStateFlow(Local())

    val state: StateFlow<HomeUiState> = combine(local, recents.observe()) { l, r ->
        HomeUiState(l.destination, l.pending, l.error, l.openInvalid, r)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), HomeUiState())

    private val openRequests = Channel<String>(Channel.BUFFERED)

    /** Bundle ids the screen should navigate to, once each. */
    val opens = openRequests.receiveAsFlow()

    fun selectDestination(destination: Destination) = local.update { it.copy(destination = destination) }

    fun createEmpty() = start(Pending.EMPTY) { bundles.create(reference = null, destination = local.value.destination) }

    fun createDemo(case: DemoCase) = start(if (case == DemoCase.CASE_C) Pending.DEMO_C else Pending.DEMO_D) { bundles.createDemo(case) }

    private fun start(kind: Pending, create: suspend () -> Bundle) {
        if (local.value.pending != null) return
        local.update { it.copy(pending = kind, error = null) }
        viewModelScope.launch {
            try {
                val bundle = create()
                recents.remember(bundle, assessment = null)
                openRequests.send(bundle.id)
            } catch (e: ApiException) {
                local.update { it.copy(error = e.message) }
            } finally {
                local.update { it.copy(pending = null) }
            }
        }
    }

    /** Opens what was typed or pasted: a bundle id, or the address of the web workbench for one. Nothing is requested until the bundle screen loads. */
    fun open(text: String) {
        val id = extractBundleId(text)
        if (id == null) {
            local.update { it.copy(openInvalid = true) }
        } else {
            local.update { it.copy(openInvalid = false) }
            viewModelScope.launch { openRequests.send(id) }
        }
    }

    fun openTextChanged() = local.update { it.copy(openInvalid = false) }

    fun forget(bundleId: String) {
        viewModelScope.launch { recents.forget(bundleId) }
    }
}
