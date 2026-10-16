package com.cargoclear.japac.ui.intake

import com.cargoclear.japac.core.data.FileImporter
import com.cargoclear.japac.core.data.InboxFiles
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** PDFs another app shared with this one, copied into the app's cache and waiting for the person to say which bundle they belong to. */
data class IntakeFiles(val files: List<InboxFiles.Imported>, val unreadable: Int)

/**
 * The shared files that are waiting for a bundle. A singleton, because the activity that receives the share and the screen that asks
 * "which bundle?" are not the same object. Receiving again replaces what was waiting (and deletes those copies).
 */
@Singleton
class PendingIntake @Inject constructor(private val importer: FileImporter) {
    private val mutable = MutableStateFlow<IntakeFiles?>(null)
    val files: StateFlow<IntakeFiles?> = mutable.asStateFlow()

    suspend fun receive(uris: List<String>) {
        if (uris.isEmpty()) return
        val result = importer.import(uris)
        mutable.value?.files?.forEach { importer.discard(it.uri) }
        mutable.value = IntakeFiles(result.imported, result.unreadable.size)
    }

    /** The person chose not to add them: delete the copies. */
    fun discard() {
        mutable.value?.files?.forEach { importer.discard(it.uri) }
        mutable.value = null
    }

    /** The files are on their way to a bundle: the upload deletes each copy when its batch ends, so only the waiting is forgotten. */
    fun handedOver() {
        mutable.value = null
    }
}
