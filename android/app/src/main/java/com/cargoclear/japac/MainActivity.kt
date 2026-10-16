package com.cargoclear.japac

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.lifecycleScope
import com.cargoclear.japac.notify.RunWatcher
import com.cargoclear.japac.ui.intake.OpenRequests
import com.cargoclear.japac.ui.intake.PendingIntake
import com.cargoclear.japac.ui.intake.sharedFileUris
import com.cargoclear.japac.ui.nav.CargoClearNavHost
import com.cargoclear.japac.ui.theme.CargoClearTheme
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import kotlinx.coroutines.launch

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    @Inject lateinit var pendingIntake: PendingIntake

    @Inject lateinit var openRequests: OpenRequests

    @Inject lateinit var runWatcher: RunWatcher

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        // a rotation recreates the activity with the same intent: it must not be taken in twice
        if (savedInstanceState == null) handle(intent)
        setContent {
            CargoClearTheme {
                CargoClearNavHost(intake = pendingIntake.files, openBundle = openRequests.bundleId, onOpenBundleHandled = openRequests::consumed)
            }
        }
    }

    override fun onStart() {
        super.onStart()
        runWatcher.appForegrounded()
    }

    override fun onStop() {
        super.onStop()
        // a rotation stops the activity too, and the person has not gone anywhere
        if (!isChangingConfigurations) runWatcher.appBackgrounded()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handle(intent)
    }

    /** What reached the app from outside: PDFs shared to it, or the request of a notification to show a bundle. */
    private fun handle(intent: Intent?) {
        val files = sharedFileUris(intent)
        if (files.isNotEmpty()) lifecycleScope.launch { pendingIntake.receive(files) }
        intent?.getStringExtra(EXTRA_BUNDLE_ID)?.let(openRequests::request)
    }

    companion object {
        /** Carried by the intent of a notification: the bundle to show. */
        const val EXTRA_BUNDLE_ID = "com.cargoclear.japac.extra.BUNDLE_ID"
    }
}
