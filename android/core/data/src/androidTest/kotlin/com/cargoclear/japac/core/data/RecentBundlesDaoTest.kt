package com.cargoclear.japac.core.data

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.cargoclear.japac.core.data.local.BundleSnapshotEntity
import com.cargoclear.japac.core.data.local.CargoClearDatabase
import com.cargoclear.japac.core.data.local.RecentBundleEntity
import com.cargoclear.japac.core.data.local.RecentBundlesDao
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** The real Room database (in memory): ordering, upsert and removal, which the JVM tests only exercise through a fake. */
class RecentBundlesDaoTest {
    private lateinit var db: CargoClearDatabase
    private lateinit var dao: RecentBundlesDao

    @Before
    fun open() {
        db = Room.inMemoryDatabaseBuilder(ApplicationProvider.getApplicationContext<Context>(), CargoClearDatabase::class.java).build()
        dao = db.recentBundles()
    }

    @After
    fun close() = db.close()

    private fun recent(id: String, opened: Long, status: String = "PENDING") =
        RecentBundleEntity(id, "ref-$id", "SG", status, 0, 3, opened)

    private fun snapshot(id: String, savedAt: Long = 1) = BundleSnapshotEntity(id, """{"id":"$id"}""", null, savedAt)

    @Test
    fun the_most_recently_opened_comes_first() = runBlocking {
        dao.remember(recent("a", 100), snapshot("a"))
        dao.remember(recent("b", 300), snapshot("b"))
        dao.remember(recent("c", 200), snapshot("c"))

        assertEquals(listOf("b", "c", "a"), dao.observeRecents().first().map { it.bundleId })
    }

    @Test
    fun remembering_a_bundle_again_updates_its_row_and_its_copy() = runBlocking {
        dao.remember(recent("a", 100, "PENDING"), snapshot("a", savedAt = 1))
        dao.remember(recent("a", 500, "MISSING_EVIDENCE"), snapshot("a", savedAt = 2))

        val rows = dao.observeRecents().first()
        assertEquals(1, rows.size)
        assertEquals("MISSING_EVIDENCE", rows.single().lastStatus)
        assertEquals(500L, rows.single().lastOpenedAt)
        assertEquals(2L, dao.snapshot("a")?.savedAt)
    }

    @Test
    fun forgetting_removes_the_row_and_the_copy_together_and_only_that_bundle() = runBlocking {
        dao.remember(recent("a", 100), snapshot("a"))
        dao.remember(recent("b", 200), snapshot("b"))

        dao.forget("a")

        assertEquals(listOf("b"), dao.observeRecents().first().map { it.bundleId })
        assertNull(dao.snapshot("a"))
        assertTrue(dao.snapshot("b") != null)
    }
}
