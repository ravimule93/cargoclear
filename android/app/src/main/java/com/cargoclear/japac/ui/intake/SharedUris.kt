package com.cargoclear.japac.ui.intake

import android.content.Intent
import android.net.Uri
import android.os.Build

/** The files a "Share" or "Share multiple" intent carries, as text: nothing for any other intent. */
fun sharedFileUris(intent: Intent?): List<String> {
    if (intent == null) return emptyList()
    val found = LinkedHashSet<String>()
    when (intent.action) {
        Intent.ACTION_SEND -> uriExtra(intent)?.let { found += it.toString() }
        Intent.ACTION_SEND_MULTIPLE -> uriListExtra(intent).forEach { found += it.toString() }
        else -> return emptyList()
    }
    // some apps put the file only in the clip
    val clip = intent.clipData
    if (found.isEmpty() && clip != null) for (i in 0 until clip.itemCount) clip.getItemAt(i).uri?.let { found += it.toString() }
    return found.toList()
}

private fun uriExtra(intent: Intent): Uri? =
    if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java) else @Suppress("DEPRECATION") intent.getParcelableExtra(Intent.EXTRA_STREAM)

private fun uriListExtra(intent: Intent): List<Uri> =
    (if (Build.VERSION.SDK_INT >= 33) intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java) else @Suppress("DEPRECATION") intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)).orEmpty()
