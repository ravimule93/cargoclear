package com.cargoclear.japac.core.data

import android.content.Context
import android.net.Uri
import com.cargoclear.japac.core.data.work.uploadFile
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Takes in files that come from outside the app (shared from another app, or scanned) by copying them into the app's private cache, where a
 * background upload can still read them later (see [InboxFiles]). The upload deletes each copy when its batch ends.
 */
interface FileImporter {
    /** Copies the files [uris] name. The ones that cannot be read are reported, not fatal. */
    suspend fun import(uris: List<String>): InboxFiles.Result

    /** Deletes one copy that is not going to be uploaded after all. */
    fun discard(uri: String)
}

@Singleton
class ContextFileImporter @Inject constructor(@ApplicationContext private val context: Context) : FileImporter {
    private val inbox = InboxFiles(InboxFiles.rootIn(context.cacheDir))

    override suspend fun import(uris: List<String>): InboxFiles.Result = inbox.import(uris.map { context.contentResolver.uploadFile(Uri.parse(it)) })

    override fun discard(uri: String) = inbox.discard(uri)
}
