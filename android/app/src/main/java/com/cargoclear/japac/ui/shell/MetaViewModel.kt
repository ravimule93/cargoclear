package com.cargoclear.japac.ui.shell

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.data.MetaRepository
import com.cargoclear.japac.core.model.Meta
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** What the app knows about the backend's mode. Port of `useMeta` (frontend/lib/hooks/useMeta.ts). */
sealed interface MetaState {
    data object Loading : MetaState
    data class Ready(val meta: Meta) : MetaState

    /** [notConfigured]: this build has no backend address at all (as opposed to one that did not answer). */
    data class Failed(val message: String, val notConfigured: Boolean = false) : MetaState
}

@HiltViewModel
class MetaViewModel @Inject constructor(private val repository: MetaRepository) : ViewModel() {
    private val mutableState = MutableStateFlow<MetaState>(MetaState.Loading)
    val state: StateFlow<MetaState> = mutableState.asStateFlow()

    private var loading: Job? = null

    init {
        load(forceRefresh = false)
    }

    fun retry() = load(forceRefresh = true)

    /** Called when the screen comes back to the foreground: a mode check that failed earlier is tried again by itself, a good one is left alone. */
    fun refreshIfFailed() {
        if (mutableState.value is MetaState.Failed) retry()
    }

    private fun load(forceRefresh: Boolean) {
        loading?.cancel()
        mutableState.value = MetaState.Loading
        loading = viewModelScope.launch {
            mutableState.value = try {
                MetaState.Ready(repository.load(forceRefresh))
            } catch (e: ApiException) {
                MetaState.Failed(e.message.orEmpty(), notConfigured = e.kind == ApiException.Kind.NOT_CONFIGURED)
            }
        }
    }
}
