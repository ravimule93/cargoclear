package com.cargoclear.japac.ui.history

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.data.AuditRepository
import com.cargoclear.japac.core.model.AuditResponse
import com.cargoclear.japac.ui.nav.BundleRoute
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * What the audit chain view shows. The chain stays on screen while a newer one is being fetched: only the very first load is a blank state
 * (as on the web). A failed load replaces the chain with the failure and a Retry.
 */
data class AuditUi(
    val audit: AuditResponse? = null,
    val loading: Boolean = true,
    val error: String? = null,
    val signing: Boolean = false,
    val signError: String? = null,
)

/** The audit chain of one bundle (port of the data side of AuditTimeline.tsx). Fetched when the History tab opens, not in the background. */
@HiltViewModel
class AuditViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val audit: AuditRepository,
) : ViewModel() {
    private val bundleId: String = checkNotNull(savedStateHandle.get<String>(BundleRoute::bundleId.name)) { "the bundle route carries no bundle id" }

    private val mutableState = MutableStateFlow(AuditUi())
    val state: StateFlow<AuditUi> = mutableState.asStateFlow()

    private var loadJob: Job? = null

    /** Fetches the chain again. A newer request replaces one that is still going, so an old answer can never overwrite a newer one. */
    fun load() {
        loadJob?.cancel()
        mutableState.update { it.copy(loading = true, error = null) }
        loadJob = viewModelScope.launch {
            try {
                val chain = audit.audit(bundleId)
                mutableState.update { it.copy(audit = chain, loading = false, error = null) }
            } catch (e: ApiException) {
                mutableState.update { it.copy(loading = false, error = e.message.orEmpty()) }
            }
        }
    }

    /** Signs the newest event of the chain, then reads the chain again. */
    fun signNow() {
        if (mutableState.value.signing) return
        mutableState.update { it.copy(signing = true, signError = null) }
        viewModelScope.launch {
            try {
                audit.signHead(bundleId)
                mutableState.update { it.copy(signing = false) }
                load()
            } catch (e: ApiException) {
                mutableState.update { it.copy(signing = false, signError = e.message.orEmpty()) }
            }
        }
    }
}
