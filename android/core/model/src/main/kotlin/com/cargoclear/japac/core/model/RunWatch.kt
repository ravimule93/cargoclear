package com.cargoclear.japac.core.model

/** A run somebody is waiting for: which bundle, and which of its runs (a bundle's stream also replays the one before). */
data class WatchedRun(val bundleId: String, val runId: String)

/** How a watched run ended. */
sealed interface RunEnd {
    data object Finished : RunEnd

    /** [message] is the run's own account of what went wrong, when it gave one. */
    data class Failed(val message: String?) : RunEnd
}

/**
 * Decides, from a bundle's status events, whether the one run being waited for is over. A stream replays the last status when it connects,
 * and that is usually the run before this one: only a terminal status of [runId] itself counts.
 */
class RunWatch(private val runId: String) {
    fun onStatus(event: StatusEvent): RunEnd? = when {
        event.runId != runId -> null
        event.state.isActive -> null
        event.state == RunState.ERROR -> RunEnd.Failed(event.message)
        else -> RunEnd.Finished
    }
}
