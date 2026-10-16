package com.cargoclear.japac.core.data

import com.cargoclear.japac.core.data.local.BundleSnapshotEntity
import com.cargoclear.japac.core.data.local.RecentBundleEntity
import com.cargoclear.japac.core.data.local.RecentBundlesDao
import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.Bundle
import com.cargoclear.japac.core.model.Status
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private class FakeDao : RecentBundlesDao {
    val recents = MutableStateFlow<Map<String, RecentBundleEntity>>(emptyMap())
    val snapshots = mutableMapOf<String, BundleSnapshotEntity>()

    override fun observeRecents(): Flow<List<RecentBundleEntity>> = recents.map { it.values.sortedByDescending { r -> r.lastOpenedAt } }
    override suspend fun snapshot(bundleId: String) = snapshots[bundleId]
    override suspend fun upsertRecent(entity: RecentBundleEntity) { recents.value = recents.value + (entity.bundleId to entity) }
    override suspend fun upsertSnapshot(entity: BundleSnapshotEntity) { snapshots[entity.bundleId] = entity }
    override suspend fun deleteRecent(bundleId: String) { recents.value = recents.value - bundleId }
    override suspend fun deleteSnapshot(bundleId: String) { snapshots.remove(bundleId) }
}

/** The repository's mapping and the saved copy, on a fake DAO (the real Room DAO is covered by an instrumented test). */
class RecentBundlesRepositoryTest {
    private val json = Json { ignoreUnknownKeys = true }
    private val newBundle = json.decodeFromString<Bundle>(TestResources.text("case_c_bundle_new.json"))
    private val analysed = json.decodeFromString<Bundle>(TestResources.text("case_c_bundle_analyzed.json"))
    private val assessment = json.decodeFromString<AssessmentIteration>(TestResources.text("case_c_assessment_missing_evidence.json"))

    private var now = 1_000L
    private val dao = FakeDao()
    private val repository = RoomRecentBundlesRepository(dao) { now }

    @Test
    fun `a bundle that was never analysed is listed with no status`() = runTest {
        repository.remember(newBundle, null)

        val recent = repository.observe().first().single()
        assertEquals(newBundle.id, recent.bundleId)
        assertNull(recent.status)
        assertEquals("SG", recent.destination)
        assertEquals(3, recent.documentCount)
        assertEquals("CASE-C-7304-DEMO", recent.reference)
        assertEquals(1_000L, recent.lastOpenedAt)
    }

    @Test
    fun `once analysed the list shows the assessment's status and iteration`() = runTest {
        repository.remember(analysed, assessment)
        val recent = repository.observe().first().single()
        assertEquals(Status.MISSING_EVIDENCE, recent.status)
        assertEquals(1, recent.iteration)
    }

    @Test
    fun `the most recently opened comes first and re-opening updates a row instead of adding one`() = runTest {
        repository.remember(newBundle, null)
        now = 2_000L
        repository.remember(analysed.copy(id = "bnd-other"), null)
        now = 3_000L
        repository.remember(newBundle, null)

        val ids = repository.observe().first().map { it.bundleId }
        assertEquals(listOf(newBundle.id, "bnd-other"), ids)
    }

    @Test
    fun `a saved copy round-trips the bundle and the assessment`() = runTest {
        now = 5_000L
        repository.remember(analysed, assessment)

        val copy = checkNotNull(repository.savedCopy(analysed.id))
        assertEquals(analysed, copy.bundle)
        assertEquals(assessment, copy.assessment)
        assertEquals(5_000L, copy.savedAt)
        assertNull(repository.savedCopy("bnd-unknown"))
    }

    @Test
    fun `a saved copy this version cannot read is no copy`() = runTest {
        dao.upsertSnapshot(BundleSnapshotEntity("bnd-old", bundleJson = """{"id":"bnd-old"}""", assessmentJson = null, savedAt = 1))
        assertNull(repository.savedCopy("bnd-old"))
    }

    @Test
    fun `forgetting removes the row and the copy from this device`() = runTest {
        repository.remember(analysed, assessment)
        repository.forget(analysed.id)
        assertTrue(repository.observe().first().isEmpty())
        assertNull(repository.savedCopy(analysed.id))
    }
}
