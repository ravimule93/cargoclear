package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.Meta
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Backend metadata (mode). One fetch per process is shared by every screen; a failed fetch is not remembered, so a retry really retries. */
interface MetaRepository {
    suspend fun load(forceRefresh: Boolean = false): Meta
}

@Singleton
class NetworkMetaRepository @Inject constructor(private val backend: Backend) : MetaRepository {
    private val lock = Mutex()
    private var cached: Meta? = null

    override suspend fun load(forceRefresh: Boolean): Meta = lock.withLock {
        cached.takeUnless { forceRefresh } ?: backend.call { meta() }.also { cached = it }
    }
}
