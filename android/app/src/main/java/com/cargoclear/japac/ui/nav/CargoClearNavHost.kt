package com.cargoclear.japac.ui.nav

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.toRoute
import com.cargoclear.japac.ui.bundle.BundleScreen
import com.cargoclear.japac.ui.home.HomeScreen
import com.cargoclear.japac.ui.intake.IntakeFiles
import com.cargoclear.japac.ui.intake.IntakeScreen
import com.cargoclear.japac.ui.settings.AboutScreen
import com.cargoclear.japac.ui.settings.SettingsScreen
import com.cargoclear.japac.ui.viewer.ViewerScreen
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.Serializable

/** Type-safe routes (docs/ANDROID_APP_PLAN.md section 7). */
@Serializable
data object Home

@Serializable
data class BundleRoute(val bundleId: String)

/** One document of a bundle, opened on [page] with, optionally, the evidence box [highlightId] chosen (the evidence row that was tapped). */
@Serializable
data class ViewerRoute(val bundleId: String, val documentId: String, val page: Int = 1, val highlightId: String? = null)

@Serializable
data object SettingsRoute

@Serializable
data object AboutRoute

/** PDFs another app shared with this one, waiting to be put in a bundle. */
@Serializable
data object IntakeRoute

/**
 * @param intake the PDFs that were shared to the app and wait for a bundle; the screen that asks for one opens when this becomes non-null
 * @param openBundle a bundle some request from outside the app (a notification) wants shown, and [onOpenBundleHandled] when it has been
 */
@Composable
fun CargoClearNavHost(
    intake: StateFlow<IntakeFiles?>,
    openBundle: StateFlow<String?>,
    onOpenBundleHandled: () -> Unit,
) {
    val navController = rememberNavController()
    val shared by intake.collectAsStateWithLifecycle()
    val requested by openBundle.collectAsStateWithLifecycle()
    LaunchedEffect(shared != null) {
        if (shared != null) navController.navigate(IntakeRoute) { launchSingleTop = true }
    }
    LaunchedEffect(requested) {
        requested?.let {
            navController.navigate(BundleRoute(it)) { launchSingleTop = true }
            onOpenBundleHandled()
        }
    }
    NavHost(navController = navController, startDestination = Home) {
        composable<Home> {
            HomeScreen(
                onOpenBundle = { id -> navController.navigate(BundleRoute(id)) },
                onOpenSettings = { navController.navigate(SettingsRoute) },
            )
        }
        composable<BundleRoute> { entry ->
            val bundleId = entry.toRoute<BundleRoute>().bundleId
            BundleScreen(
                onBack = { navController.popBackStack() },
                onOpenViewer = { documentId, page, highlightId -> navController.navigate(ViewerRoute(bundleId, documentId, page ?: 1, highlightId)) },
            )
        }
        composable<ViewerRoute> {
            ViewerScreen(onBack = { navController.popBackStack() })
        }
        composable<SettingsRoute> {
            SettingsScreen(onBack = { navController.popBackStack() }, onOpenAbout = { navController.navigate(AboutRoute) })
        }
        composable<AboutRoute> {
            AboutScreen(onBack = { navController.popBackStack() })
        }
        composable<IntakeRoute> {
            IntakeScreen(
                onOpenBundle = { id -> navController.navigate(BundleRoute(id)) { popUpTo<IntakeRoute> { inclusive = true } } },
                onDone = { navController.popBackStack() },
            )
        }
    }
}
