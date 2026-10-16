package com.cargoclear.japac.ui.scan

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.platform.LocalContext
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailability
import com.google.mlkit.vision.documentscanner.GmsDocumentScannerOptions
import com.google.mlkit.vision.documentscanner.GmsDocumentScanning
import com.google.mlkit.vision.documentscanner.GmsDocumentScanningResult

/** The system document scanner, or the fact that it cannot be offered here. */
class DocumentScanner(val available: Boolean, val start: () -> Unit)

/** The most pages one scan can hold: a PDF this long still goes up well within the server's size limit. */
private const val MAX_PAGES = 20

/**
 * Google's on-device document scanner (ML Kit): it finds the page edges, straightens and cleans the photo, and hands back a PDF, with no
 * camera permission asked of this app. It comes with Google Play services, so [DocumentScanner.available] is false on a phone without them,
 * and the choice to scan is simply not offered there.
 */
@Composable
fun rememberDocumentScanner(onScanned: (List<String>) -> Unit, onFailed: () -> Unit): DocumentScanner {
    val context = LocalContext.current
    val scanned by rememberUpdatedState(onScanned)
    val failed by rememberUpdatedState(onFailed)
    val available = remember(context) {
        context.findActivity() != null && GoogleApiAvailability.getInstance().isGooglePlayServicesAvailable(context) == ConnectionResult.SUCCESS
    }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { result ->
        // cancelling the scanner is not an error: only a scan that ended without a PDF is
        if (result.resultCode == Activity.RESULT_OK) {
            val pdf = GmsDocumentScanningResult.fromActivityResultIntent(result.data)?.pdf?.uri
            if (pdf != null) scanned(listOf(pdf.toString())) else failed()
        }
    }
    return remember(available, launcher, context) {
        DocumentScanner(available) {
            val activity = context.findActivity()
            if (activity == null) {
                failed()
            } else {
                val options = GmsDocumentScannerOptions.Builder()
                    .setGalleryImportAllowed(true)
                    .setPageLimit(MAX_PAGES)
                    .setResultFormats(GmsDocumentScannerOptions.RESULT_FORMAT_PDF)
                    .setScannerMode(GmsDocumentScannerOptions.SCANNER_MODE_FULL)
                    .build()
                GmsDocumentScanning.getClient(options).getStartScanIntent(activity)
                    .addOnSuccessListener { launcher.launch(IntentSenderRequest.Builder(it).build()) }
                    .addOnFailureListener { failed() }
            }
        }
    }
}

private fun Context.findActivity(): Activity? {
    var current: Context? = this
    while (current is ContextWrapper) {
        if (current is Activity) return current
        current = current.baseContext
    }
    return null
}
