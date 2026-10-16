package com.cargoclear.japac.core.model

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/** The open correction editor: which value of which document is being corrected, and the form. */
data class CorrectionEditor(val documentName: String, val draft: CorrectionDraft)

/**
 * What the person is doing with corrections right now, apart from what the server holds: the editor that is open, and the undo that is
 * in flight (or failed). Kept in the view model, so a rotation does not lose a half-typed value.
 */
data class CorrectionsUi(
    val editor: CorrectionEditor? = null,
    val revertingId: String? = null,
    val revertError: String? = null,
) {
    /** Opens the editor on one value (the web's Edit button). Asking again for the same value keeps what was typed. */
    fun opened(documentId: String, documentName: String, path: String, current: CellValue?): CorrectionsUi {
        val open = editor
        if (open != null && open.draft.documentId == documentId && open.draft.path == path) return this
        return copy(editor = CorrectionEditor(documentName, CorrectionDraft(documentId, path).loaded(current)))
    }

    fun closed(): CorrectionsUi = copy(editor = null)

    fun edited(change: (CorrectionDraft) -> CorrectionDraft): CorrectionsUi = editor?.let { copy(editor = it.copy(draft = change(it.draft))) } ?: this

    fun saving(): CorrectionsUi = edited { it.saving() }

    fun saveFailed(message: String): CorrectionsUi = edited { it.failed(message) }

    fun reverting(correctionId: String): CorrectionsUi = copy(revertingId = correctionId, revertError = null)

    fun revertFailed(message: String): CorrectionsUi = copy(revertingId = null, revertError = message)

    fun reverted(): CorrectionsUi = copy(revertingId = null)

    /** The shown bundle changed (a retry reloads it): nothing of the old one stays open. */
    fun reset(): CorrectionsUi = CorrectionsUi()
}

/** What of an open editor survives the system ending the app's process: where it points and what was typed. Not that a save was under way, nor its failure. */
@Serializable
private data class SavedEditor(
    val documentName: String,
    val documentId: String,
    val path: String,
    val value: String,
    val unit: String,
    val reason: String,
    val clear: Boolean,
    val touched: Boolean,
)

/** The editor as text for the saved state of the screen (a `SavedStateHandle` holds strings). */
fun CorrectionEditor.toSavedState(): String =
    Json.encodeToString(
        SavedEditor(documentName, draft.documentId, draft.path, draft.value, draft.unit, draft.reason, draft.clear, draft.touched),
    )

/** The editor [toSavedState] wrote, or null for nothing or for text that is not that (an old format, a damaged state): then there is simply no editor open. */
fun correctionEditorFromSavedState(text: String?): CorrectionEditor? {
    if (text.isNullOrEmpty()) return null
    val saved = try {
        Json.decodeFromString<SavedEditor>(text)
    } catch (e: kotlinx.serialization.SerializationException) {
        return null
    } catch (e: IllegalArgumentException) {
        return null
    }
    return CorrectionEditor(
        saved.documentName,
        CorrectionDraft(saved.documentId, saved.path, saved.value, saved.unit, saved.reason, saved.clear, saved.touched),
    )
}
