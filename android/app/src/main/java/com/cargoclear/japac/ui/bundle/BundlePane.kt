package com.cargoclear.japac.ui.bundle

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import com.cargoclear.japac.core.model.WorkbenchState
import com.cargoclear.japac.ui.nav.ViewerRoute
import com.cargoclear.japac.ui.viewer.ViewerScreen
import kotlinx.serialization.Serializable

/** The pane's first destination: the documents of the bundle. */
@Serializable
data object PaneDocuments

/**
 * The right-hand pane of the two-pane bundle screen: the document list, and the viewer once a document (or an evidence row) is chosen. It is
 * a navigation host of its own, so the viewer, its arguments and its view-model work exactly as they do full-screen on a phone, and Back
 * inside the pane returns to the list.
 */
@Composable
fun BundlePane(
    navController: NavHostController,
    bundleId: String,
    state: WorkbenchState,
    onSelectDocument: (String) -> Unit,
    onAddDocuments: () -> Unit,
    modifier: Modifier = Modifier,
) {
    NavHost(navController = navController, startDestination = PaneDocuments, modifier = modifier) {
        composable<PaneDocuments> {
            DocumentsTab(
                state,
                onOpen = { id ->
                    onSelectDocument(id)
                    navController.openInPane(ViewerRoute(bundleId, id))
                },
                onAddDocuments = onAddDocuments,
            )
        }
        composable<ViewerRoute> { ViewerScreen(onBack = { navController.popBackStack() }) }
    }
}

/** Shows a document in the pane in place of whichever one is there: the viewer is never stacked on itself, so Back always reaches the list. */
fun NavHostController.openInPane(route: ViewerRoute) {
    navigate(route) { popUpTo<PaneDocuments>() }
}
