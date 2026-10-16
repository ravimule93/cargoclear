package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.AuditResponse
import com.cargoclear.japac.core.model.AuditSignature
import javax.inject.Inject
import javax.inject.Singleton

/** The tamper-evident history of a bundle. Every failure is an [ApiException]. */
interface AuditRepository {
    /** The events, whether the chain verifies, and what its signatures say. */
    suspend fun audit(bundleId: String): AuditResponse

    /** Signs the newest event of the chain (when a run could not, or events came after it). Signing a head that is already signed changes nothing. */
    suspend fun signHead(bundleId: String): AuditSignature
}

@Singleton
class NetworkAuditRepository @Inject constructor(private val backend: Backend) : AuditRepository {
    override suspend fun audit(bundleId: String): AuditResponse = backend.call { getAudit(bundleId) }

    override suspend fun signHead(bundleId: String): AuditSignature = backend.call { signAuditHead(bundleId) }
}
