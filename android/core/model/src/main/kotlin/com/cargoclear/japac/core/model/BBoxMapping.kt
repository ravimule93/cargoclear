package com.cargoclear.japac.core.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

/** Per-page preprocessing metadata (`transform-metadata`). The backend sends untyped dicts, so only the geometry is required. */
@Serializable
data class TransformMetadata(
    val page: Int,
    /** Original one-indexed PDF page. Absent on metadata written before provenance upgrades. */
    @SerialName("source_page") val sourcePage: Int? = null,
    @SerialName("processed_page") val processedPage: Int? = null,
    @SerialName("document_id") val documentId: String? = null,
    @SerialName("deskew_deg") val deskewDeg: Double = 0.0,
    @SerialName("deskew_applied") val deskewApplied: Boolean? = null,
    val rotation: Int = 0,
    @SerialName("rotation_applied") val rotationApplied: Boolean? = null,
    /** Normalised processed-to-source 3x3, present for newly transformed records. */
    @SerialName("processed_to_source_affine") val processedToSourceAffine: List<List<Double>>? = null,
    /** the skew that was measured, whether or not it was corrected */
    @SerialName("deskew_detected_deg") val deskewDetectedDeg: Double? = null,
    /** why no deskew was applied: disabled | below_threshold | above_limit */
    @SerialName("deskew_skipped") val deskewSkipped: String? = null,
    /** what the model was shown: "bw" (1-bit) or "gray" */
    @SerialName("image_mode") val imageMode: String? = null,
    /** where the page image the model was shown is stored */
    @SerialName("processed_uri") val processedUri: String? = null,
    @SerialName("artifact_index") val artifactIndex: Int? = null,
    @SerialName("artifact_page") val artifactPage: Int? = null,
    @SerialName("artifact_id") val artifactId: String? = null,
    @SerialName("split_offset") val splitOffset: Int = 0,
    /** A crop applied to the page, if any; the viewer does not use it (the affine already carries any crop), so it is kept as it came. */
    val crop: JsonElement? = null,
    val width: Int = 0,
    val height: Int = 0,
)

/** Answer of `GET /bundles/{id}/documents/{doc}/transform-metadata`: one entry per page of the document. */
@Serializable
data class TransformMetadataResponse(
    @SerialName("document_id") val documentId: String,
    @SerialName("transform_meta") val transformMeta: List<TransformMetadata>,
)

data class CanvasRect(val x: Double, val y: Double, val w: Double, val h: Double)

/** Port of frontend/lib/bbox.ts: a 0-1000 box to a rectangle on a canvas of the given size. */
fun mapBBoxToCanvas(bbox: BBox, canvasWidth: Double, canvasHeight: Double): CanvasRect = CanvasRect(
    x = bbox.xmin / 1000 * canvasWidth,
    y = bbox.ymin / 1000 * canvasHeight,
    w = maxOf(0.0, (bbox.xmax - bbox.xmin) / 1000 * canvasWidth),
    h = maxOf(0.0, (bbox.ymax - bbox.ymin) / 1000 * canvasHeight),
)

private fun isAffine(value: List<List<Double>>?): Boolean =
    value != null && value.size == 3 && value.all { row -> row.size == 3 && row.all { it.isFinite() } }

fun applyAffine(matrix: List<List<Double>>, x: Double, y: Double): Pair<Double, Double> = Pair(
    matrix[0][0] * x + matrix[0][1] * y + matrix[0][2],
    matrix[1][0] * x + matrix[1][1] * y + matrix[1][2],
)

private fun clamp(value: Double): Double = value.coerceIn(0.0, 1000.0)

private fun mapThroughAffine(bbox: BBox, page: Int, matrix: List<List<Double>>): BBox {
    val corners = listOf(
        applyAffine(matrix, bbox.xmin, bbox.ymin),
        applyAffine(matrix, bbox.xmax, bbox.ymin),
        applyAffine(matrix, bbox.xmin, bbox.ymax),
        applyAffine(matrix, bbox.xmax, bbox.ymax),
    )
    val xs = corners.map { it.first }
    val ys = corners.map { it.second }
    return BBox(page = page, ymin = clamp(ys.min()), xmin = clamp(xs.min()), ymax = clamp(ys.max()), xmax = clamp(xs.max()))
}

/**
 * Maps a normalised box emitted for a processed page back to the original PDF orientation (port of frontend/lib/transform-bbox.ts).
 *
 * New metadata names the original page as `sourcePage`; older records use `page`. Artifact identifiers and `splitOffset` identify
 * persisted split PDFs but never move source pages. A page that was only rotated (0/90/180/270) maps by exact corner swaps; a page that
 * was also deskewed (`deskewApplied`) maps through `processedToSourceAffine`, the reversible 3x3 the backend recorded: the four corners
 * of the box go through it and the result is their bounding box. Absent or unusable metadata leaves the box where it is.
 */
fun mapProcessedBBoxToOriginal(bbox: BBox, transform: TransformMetadata?): BBox {
    val page = transform?.sourcePage ?: bbox.page
    val affine = transform?.processedToSourceAffine
    if (transform?.deskewApplied == true && isAffine(affine)) return mapThroughAffine(bbox, page, affine!!)
    return when (transform?.rotation) {
        90 -> BBox(page, ymin = 1000 - bbox.xmax, xmin = bbox.ymin, ymax = 1000 - bbox.xmin, xmax = bbox.ymax)
        180 -> BBox(page, ymin = 1000 - bbox.ymax, xmin = 1000 - bbox.xmax, ymax = 1000 - bbox.ymin, xmax = 1000 - bbox.xmin)
        270 -> BBox(page, ymin = bbox.xmin, xmin = 1000 - bbox.ymax, ymax = bbox.xmax, xmax = 1000 - bbox.ymin)
        else -> if (transform?.sourcePage != null) bbox.copy(page = page) else bbox
    }
}
