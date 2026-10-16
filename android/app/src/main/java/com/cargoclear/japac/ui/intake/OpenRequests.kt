package com.cargoclear.japac.ui.intake

import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * A request from outside the app to show one bundle (the tap on a "your analysis finished" notification). A singleton for the same reason as
 * [PendingIntake]: the activity that gets the intent is not the navigation that acts on it.
 */
@Singleton
class OpenRequests @Inject constructor() {
    private val mutable = MutableStateFlow<String?>(null)
    val bundleId: StateFlow<String?> = mutable.asStateFlow()

    fun request(bundleId: String) {
        mutable.value = bundleId
    }

    /** The navigation has acted on it. */
    fun consumed() {
        mutable.value = null
    }
}
