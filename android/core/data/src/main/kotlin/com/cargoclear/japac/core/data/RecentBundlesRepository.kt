package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.data.local.BundleSnapshotEntity
import com.cargoclear.japac.core.data.local.RecentBundleEntity
import com.cargoclear.japac.core.data.local.RecentBundlesDao
import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.Bundle
import com.cargoclear.japac.core.model.Status
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

/** A bundle in the "recent" list. [status] is null while it has never been assessed. */
data class RecentBundle(
    val bundleId: String,
    val reference: String?,
    val destination: String,
    val status: Status?,
    val iteration: Int,
    val documentCount: Int,
    val lastOpenedAt: Long,
)

/** What this device last saw of a bundle, for reading it without the server. */
data class SavedCopy(val bundle: Bundle, val assessment: AssessmentIteration?, val savedAt: Long)

/** The bundles this device has opened (the backend has no list endpoint and no user identity) and their last-seen state. */
interface RecentBundlesRepository {
    fun observe(): Flow<List<RecentBundle>>

    /** Records that this bundle was seen now, in this state. */
    suspend fun remember(bundle: Bundle, assessment: AssessmentIteration?)

    suspend fun savedCopy(bundleId: String): SavedCopy?

    /** Removes the bundle from this device only; it stays on the server. */
    suspend fun forget(bundleId: String)
}

@Singleton
class RoomRecentBundlesRepository @Inject constructor(
    private val dao: RecentBundlesDao,
) : RecentBundlesRepository {
    private val json = Backend.defaultJson
    private var clock: () -> Long = System::currentTimeMillis

    /** For tests: a controllable clock. */
    internal constructor(dao: RecentBundlesDao, clock: () -> Long) : this(dao) {
        this.clock = clock
    }

    override fun observe(): Flow<List<RecentBundle>> = dao.observeRecents().map { rows ->
        rows.map {
            RecentBundle(it.bundleId, it.reference, it.destination, Status.fromWire(it.lastStatus), it.lastIteration, it.documentCount, it.lastOpenedAt)
        }
    }

    override suspend fun remember(bundle: Bundle, assessment: AssessmentIteration?) {
        val now = clock()
        dao.remember(
            RecentBundleEntity(
                bundleId = bundle.id,
                reference = bundle.reference,
                destination = bundle.destinationCountry,
                lastStatus = assessment?.status ?: bundle.status,
                lastIteration = assessment?.iteration ?: bundle.currentIteration,
                documentCount = bundle.documents.size,
                lastOpenedAt = now,
            ),
            BundleSnapshotEntity(
                bundleId = bundle.id,
                bundleJson = json.encodeToString(Bundle.serializer(), bundle),
                assessmentJson = assessment?.let { json.encodeToString(AssessmentIteration.serializer(), it) },
                savedAt = now,
            ),
        )
    }

    override suspend fun savedCopy(bundleId: String): SavedCopy? {
        val row = dao.snapshot(bundleId) ?: return null
        return try {
            SavedCopy(
                bundle = json.decodeFromString(Bundle.serializer(), row.bundleJson),
                assessment = row.assessmentJson?.let { json.decodeFromString(AssessmentIteration.serializer(), it) },
                savedAt = row.savedAt,
            )
        } catch (_: SerializationException) {
            null // a copy this version cannot read is no copy
        }
    }

    override suspend fun forget(bundleId: String) = dao.forget(bundleId)
}
