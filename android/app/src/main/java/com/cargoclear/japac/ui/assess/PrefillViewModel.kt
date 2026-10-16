package com.cargoclear.japac.ui.assess

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cargoclear.japac.core.data.ApiException
import com.cargoclear.japac.core.data.PrefillFiles
import com.cargoclear.japac.core.model.PrefillFormat
import com.cargoclear.japac.ui.nav.BundleRoute
import dagger.hilt.android.lifecycle.HiltViewModel
import java.io.File
import javax.inject.Inject
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** A pack that has been downloaded and is ready to hand to the share sheet. */
data class PrefillShare(val file: File, val format: PrefillFormat)

data class PrefillUi(
    /** the format being downloaded, or null */
    val busy: PrefillFormat? = null,
    val error: String? = null,
)

/**
 * Downloads the pre-fill pack of an assessment into the app's cache and announces it once, for the screen to share (the browser's
 * "Download" link has no counterpart on a phone: the system share sheet offers Files, Drive, mail and the rest).
 */
@HiltViewModel
class PrefillViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val files: PrefillFiles,
) : ViewModel() {
    private val bundleId: String = checkNotNull(savedStateHandle.get<String>(BundleRoute::bundleId.name)) { "the bundle route carries no bundle id" }

    private val mutableState = MutableStateFlow(PrefillUi())
    val state: StateFlow<PrefillUi> = mutableState.asStateFlow()

    private val ready = Channel<PrefillShare>(Channel.BUFFERED)

    /** Each downloaded pack arrives here once. */
    val shares: Flow<PrefillShare> = ready.receiveAsFlow()

    fun share(iteration: Int, format: PrefillFormat) {
        if (mutableState.value.busy != null) return
        mutableState.update { PrefillUi(busy = format) }
        viewModelScope.launch {
            try {
                ready.send(PrefillShare(files.download(bundleId, iteration, format), format))
                mutableState.update { PrefillUi() }
            } catch (e: ApiException) {
                mutableState.update { PrefillUi(error = e.message.orEmpty()) }
            }
        }
    }

}
