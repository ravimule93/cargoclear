package com.cargoclear.japac.ui.intake

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.data.BundleRepository
import com.cargoclear.japac.core.data.RecentBundle
import com.cargoclear.japac.core.data.RecentBundlesRepository
import com.cargoclear.japac.core.data.work.UploadScheduler
import com.cargoclear.japac.core.model.Destination
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class IntakeUi(
    val destination: Destination = Destination.SINGAPORE,
    val busy: Boolean = false,
    val error: String? = null,
)

/**
 * "Which bundle do these shared files belong to?": into a recent bundle, or into a new one. The files go up in the background through
 * the same scheduler as files picked inside the app, and the bundle then opens so the person can follow along.
 */
@HiltViewModel
class IntakeViewModel @Inject constructor(
    private val pending: PendingIntake,
    private val bundles: BundleRepository,
    private val recents: RecentBundlesRepository,
    private val uploads: UploadScheduler,
) : ViewModel() {
    val files: StateFlow<IntakeFiles?> = pending.files

    val recent: StateFlow<List<RecentBundle>> = recents.observe().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    private val mutableState = MutableStateFlow(IntakeUi())
    val state: StateFlow<IntakeUi> = mutableState.asStateFlow()

    private val openRequests = Channel<String>(Channel.BUFFERED)

    /** The bundle to show once the files are on their way, once each. */
    val opens = openRequests.receiveAsFlow()

    fun selectDestination(destination: Destination) = mutableState.update { it.copy(destination = destination) }

    fun addTo(bundle: RecentBundle) {
        if (mutableState.value.busy) return // a bundle is being made for these files
        val waiting = files.value?.files?.takeIf { it.isNotEmpty() } ?: return
        uploads.enqueue(bundle.bundleId, waiting.map { it.uri }, bundle.iteration)
        pending.handedOver()
        viewModelScope.launch { openRequests.send(bundle.bundleId) }
    }

    fun createAndAdd() {
        val waiting = files.value?.files?.takeIf { it.isNotEmpty() } ?: return
        if (mutableState.value.busy) return
        mutableState.update { it.copy(busy = true, error = null) }
        viewModelScope.launch {
            try {
                val bundle = bundles.create(reference = null, destination = mutableState.value.destination)
                recents.remember(bundle, assessment = null)
                uploads.enqueue(bundle.id, waiting.map { it.uri }, 0)
                pending.handedOver()
                openRequests.send(bundle.id)
            } catch (e: ApiException) {
                mutableState.update { it.copy(error = e.message.orEmpty()) }
            } finally {
                mutableState.update { it.copy(busy = false) }
            }
        }
    }

    /**
     * The person backed out: the copies are not wanted any more. Not while a bundle is being made for them: the files are on their way into
     * it, and deleting them now would leave an empty bundle and an upload that cannot find its files. True when they were let go.
     */
    fun cancel(): Boolean {
        if (mutableState.value.busy) return false
        pending.discard()
        return true
    }
}
