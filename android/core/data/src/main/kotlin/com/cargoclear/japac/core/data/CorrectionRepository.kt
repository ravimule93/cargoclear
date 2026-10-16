package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.CorrectionRecord
import com.cargoclear.japac.core.model.CorrectionRequest
import com.cargoclear.japac.core.model.CorrectionsResponse
import com.cargoclear.japac.core.model.ExtractedDoc
import com.cargoclear.japac.core.model.RevertCorrectionRequest
import javax.inject.Inject
import javax.inject.Singleton

/** Corrections by the authorised agent, and the extraction they are made against. Every failure is an [ApiException]. */
interface CorrectionRepository {
    /** Every entry, the overlay in force now, and how many changes the latest assessment lacks. */
    suspend fun corrections(bundleId: String): CorrectionsResponse

    /** States what the document actually says at one address; saving the value as it is records a confirmation. Changes nothing until recomputed. */
    suspend fun submit(bundleId: String, request: CorrectionRequest): CorrectionRecord

    /** Undoes a correction that is in force (an entry is appended; the history is kept). */
    suspend fun revert(bundleId: String, correctionId: String): CorrectionRecord

    /** The extraction behind assessment [iteration], corrections laid on. */
    suspend fun extractions(bundleId: String, iteration: Int): List<ExtractedDoc>
}

@Singleton
class NetworkCorrectionRepository @Inject constructor(private val backend: Backend) : CorrectionRepository {
    override suspend fun corrections(bundleId: String): CorrectionsResponse = backend.call { getCorrections(bundleId) }

    override suspend fun submit(bundleId: String, request: CorrectionRequest): CorrectionRecord = backend.call { createCorrection(bundleId, request) }

    override suspend fun revert(bundleId: String, correctionId: String): CorrectionRecord =
        backend.call { revertCorrection(bundleId, correctionId, RevertCorrectionRequest()) }

    override suspend fun extractions(bundleId: String, iteration: Int): List<ExtractedDoc> = backend.call { getExtractions(bundleId, iteration) }
}
