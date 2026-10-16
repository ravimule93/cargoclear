package com.cargoclear.japac.notify

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cargoclear.japac.core.data.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/** The choice "tell me when an analysis finishes", for the screens that offer it (the bundle screen while a run goes, and Settings). */
@HiltViewModel
class NotifyViewModel @Inject constructor(private val settings: SettingsRepository) : ViewModel() {
    val enabled: StateFlow<Boolean> = settings.notifyRunFinished.stateIn(viewModelScope, SharingStarted.Eagerly, false)

    fun set(on: Boolean) {
        viewModelScope.launch { settings.setNotifyRunFinished(on) }
    }
}
