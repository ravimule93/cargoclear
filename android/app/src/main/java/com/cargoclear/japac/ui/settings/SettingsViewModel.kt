package com.cargoclear.japac.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cargoclear.japac.core.data.DocumentFiles
import com.cargoclear.japac.core.data.PrefillFiles
import com.cargoclear.japac.core.data.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val settings: SettingsRepository,
    private val files: DocumentFiles,
    private val prefill: PrefillFiles,
) : ViewModel() {
    val viewerSecure: StateFlow<Boolean> = settings.viewerSecure.stateIn(viewModelScope, SharingStarted.Eagerly, true)

    val notifyRunFinished: StateFlow<Boolean> = settings.notifyRunFinished.stateIn(viewModelScope, SharingStarted.Eagerly, false)

    private val mutableCacheBytes = MutableStateFlow(0L)

    /** How much the downloaded documents and pre-fill packs take on this phone. */
    val cacheBytes: StateFlow<Long> = mutableCacheBytes.asStateFlow()

    init {
        refreshCacheSize()
    }

    fun setViewerSecure(secure: Boolean) {
        viewModelScope.launch { settings.setViewerSecure(secure) }
    }

    fun setNotifyRunFinished(notify: Boolean) {
        viewModelScope.launch { settings.setNotifyRunFinished(notify) }
    }

    fun clearCache() {
        viewModelScope.launch {
            files.clear()
            prefill.clear()
            refreshCacheSize()
        }
    }

    private fun refreshCacheSize() {
        viewModelScope.launch { mutableCacheBytes.value = files.sizeBytes() + prefill.sizeBytes() }
    }
}
