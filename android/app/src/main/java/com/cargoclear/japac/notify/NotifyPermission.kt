package com.cargoclear.japac.notify

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat

/**
 * Turning "tell me when an analysis finishes" on needs the system's permission to show notifications (from Android 13). This returns the
 * function that does it: it asks when it has to, and reports the outcome through [onResult] (true: on; false: off, because the person
 * declined or the setting was turned off). The choice is stored only when the permission is there.
 */
@Composable
fun rememberNotifyEnabler(onResult: (on: Boolean, denied: Boolean) -> Unit): (Boolean) -> Unit {
    val context = LocalContext.current
    val result by rememberUpdatedState(onResult)
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted -> result(granted, !granted) }
    return { wantOn ->
        when {
            !wantOn -> result(false, false)
            Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED -> result(true, false)
            else -> launcher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
}
