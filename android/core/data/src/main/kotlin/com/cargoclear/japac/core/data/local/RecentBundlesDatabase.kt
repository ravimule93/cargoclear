package com.cargoclear.japac.core.data.local

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.RoomDatabase
import androidx.room.Transaction
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

/**
 * A bundle this device has opened. There is no list-bundles endpoint and no user identity on the backend, so this table IS the person's
 * list: forgetting a row loses the only way back to that bundle from this phone (the bundle itself stays on the server).
 */
@Entity(tableName = "recent_bundles")
data class RecentBundleEntity(
    @PrimaryKey @ColumnInfo(name = "bundle_id") val bundleId: String,
    val reference: String?,
    val destination: String,
    /** the assessment status, or the bundle's own `PENDING` */
    @ColumnInfo(name = "last_status") val lastStatus: String,
    @ColumnInfo(name = "last_iteration") val lastIteration: Int,
    @ColumnInfo(name = "document_count") val documentCount: Int,
    @ColumnInfo(name = "last_opened_at") val lastOpenedAt: Long,
)

/** The last bundle and latest assessment this device saw, as JSON, so a bundle can still be read when the server cannot be reached. */
@Entity(tableName = "bundle_snapshots")
data class BundleSnapshotEntity(
    @PrimaryKey @ColumnInfo(name = "bundle_id") val bundleId: String,
    @ColumnInfo(name = "bundle_json") val bundleJson: String,
    @ColumnInfo(name = "assessment_json") val assessmentJson: String?,
    @ColumnInfo(name = "saved_at") val savedAt: Long,
)

@Dao
interface RecentBundlesDao {
    @Query("SELECT * FROM recent_bundles ORDER BY last_opened_at DESC")
    fun observeRecents(): Flow<List<RecentBundleEntity>>

    @Query("SELECT * FROM bundle_snapshots WHERE bundle_id = :bundleId")
    suspend fun snapshot(bundleId: String): BundleSnapshotEntity?

    @Upsert
    suspend fun upsertRecent(entity: RecentBundleEntity)

    @Upsert
    suspend fun upsertSnapshot(entity: BundleSnapshotEntity)

    @Query("DELETE FROM recent_bundles WHERE bundle_id = :bundleId")
    suspend fun deleteRecent(bundleId: String)

    @Query("DELETE FROM bundle_snapshots WHERE bundle_id = :bundleId")
    suspend fun deleteSnapshot(bundleId: String)

    @Transaction
    suspend fun remember(recent: RecentBundleEntity, snapshot: BundleSnapshotEntity) {
        upsertRecent(recent)
        upsertSnapshot(snapshot)
    }

    @Transaction
    suspend fun forget(bundleId: String) {
        deleteRecent(bundleId)
        deleteSnapshot(bundleId)
    }
}

@Database(entities = [RecentBundleEntity::class, BundleSnapshotEntity::class], version = 1, exportSchema = true)
abstract class CargoClearDatabase : RoomDatabase() {
    abstract fun recentBundles(): RecentBundlesDao
}
