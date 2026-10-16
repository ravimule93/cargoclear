package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.Bundle
import com.cargoclear.japac.core.model.CreateBundleRequest
import com.cargoclear.japac.core.model.Destination
import com.cargoclear.japac.core.model.RunResponse
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow

/** The two demo journeys (`POST /demo/case-c`, `/demo/case-d`); they exist only on a backend in demo mode. */
enum class DemoCase { CASE_C, CASE_D }

/** Bundles as the backend holds them. Every failure is an [ApiException]. */
interface BundleRepository {
    suspend fun create(reference: String?, destination: Destination): Bundle

    suspend fun createDemo(case: DemoCase): Bundle

    suspend fun bundle(id: String): Bundle

    /** The latest assessment, or null when the bundle has not been analysed yet (the backend answers 404 for that). */
    suspend fun latestAssessment(id: String): AssessmentIteration?

    suspend fun iterations(id: String): List<AssessmentIteration>

    /** Starts the first full analysis. The answer only says the run was accepted; its progress and result arrive on [events]. */
    suspend fun analyze(id: String): RunResponse

    /** Runs the pipeline again over the documents now in the bundle. */
    suspend fun reassess(id: String): RunResponse

    /** Re-runs the checks on the stored extraction with the corrections applied (no document is read, no model is called). */
    suspend fun recompute(id: String): RunResponse

    /** The bundle's live stream; reconnects by itself until the collector stops. */
    fun events(id: String): Flow<StreamEvent>
}

@Singleton
class NetworkBundleRepository @Inject constructor(
    private val backend: Backend,
    private val stream: BundleStreamClient,
) : BundleRepository {
    override suspend fun create(reference: String?, destination: Destination): Bundle =
        backend.call { createBundle(CreateBundleRequest(reference = reference?.trim()?.takeIf { it.isNotEmpty() }, destinationCountry = destination.code)) }

    override suspend fun createDemo(case: DemoCase): Bundle = backend.call {
        when (case) {
            DemoCase.CASE_C -> createCaseCDemo()
            DemoCase.CASE_D -> createCaseDDemo()
        }
    }

    override suspend fun bundle(id: String): Bundle = backend.call { getBundle(id) }

    override suspend fun latestAssessment(id: String): AssessmentIteration? =
        try {
            backend.call { getAssessment(id) }
        } catch (e: ApiException) {
            if (e.isNotFound) null else throw e
        }

    override suspend fun iterations(id: String): List<AssessmentIteration> = backend.call { listIterations(id) }

    override suspend fun analyze(id: String): RunResponse = backend.call { analyze(id) }

    override suspend fun reassess(id: String): RunResponse = backend.call { reassess(id) }

    override suspend fun recompute(id: String): RunResponse = backend.call { recompute(id) }

    override fun events(id: String): Flow<StreamEvent> = stream.events(id)
}
