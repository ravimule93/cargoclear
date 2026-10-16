package com.cargoclear.japac.core.model

import kotlin.coroutines.cancellation.CancellationException

/**
 * [runCatching] for a block that calls suspending functions. A cancelled coroutine is being told to stop, not failing, so the cancellation
 * goes on: swallowing it lets the code after the call carry on (and act) in a coroutine whose work nobody wants any more.
 */
inline fun <T> runCatchingCancellable(block: () -> T): Result<T> =
    try {
        Result.success(block())
    } catch (e: CancellationException) {
        throw e
    } catch (e: Throwable) {
        Result.failure(e)
    }
