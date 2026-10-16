package com.cargoclear.japac.ui.a11y

import androidx.compose.runtime.Composable
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import com.cargoclear.japac.Assets
import com.cargoclear.japac.Fixtures
import com.cargoclear.japac.core.model.BBox
import com.cargoclear.japac.core.model.DocumentRecord
import com.cargoclear.japac.core.model.Highlight
import com.cargoclear.japac.core.model.Severity
import com.cargoclear.japac.core.model.TransformMetadata
import com.cargoclear.japac.core.model.ViewerState
import com.cargoclear.japac.ui.viewer.PdfPages
import com.cargoclear.japac.ui.viewer.PdfRendererPages
import com.cargoclear.japac.ui.viewer.ViewerContent
import kotlinx.coroutines.runBlocking
import com.cargoclear.japac.core.data.RecentBundle
import com.cargoclear.japac.core.data.InboxFiles
import com.cargoclear.japac.core.model.AppMode
import com.cargoclear.japac.core.model.CorrectionsUi
import com.cargoclear.japac.core.model.Status
import com.cargoclear.japac.core.model.WorkbenchState
import com.cargoclear.japac.core.model.readCell
import com.cargoclear.japac.ui.bundle.BundleContent
import com.cargoclear.japac.ui.history.AuditUi
import com.cargoclear.japac.ui.home.HomeContent
import com.cargoclear.japac.ui.home.HomeUiState
import com.cargoclear.japac.ui.intake.IntakeContent
import com.cargoclear.japac.ui.intake.IntakeFiles
import com.cargoclear.japac.ui.intake.IntakeUi
import com.cargoclear.japac.ui.settings.AboutContent
import com.cargoclear.japac.ui.settings.SettingsContent
import com.cargoclear.japac.ui.shell.MetaState
import com.cargoclear.japac.ui.theme.CargoClearTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * An audit of the controls on every key screen, run on a device: each thing a person can tap, toggle or select must have a name a screen reader can
 * say, a role it can announce, and a touch target of at least 48 dp each way (Material's and WCAG 2.2's 2.5.8 floor is lower; 48 dp is the platform's guidance).
 * It reads the merged semantics tree: what TalkBack walks. It cannot judge reading order or whether a name is a good one (that is the manual pass in
 * the README), but it fails when a control is added with no label, no role, or a target that is too small to hit.
 */
class AccessibilityAuditTest {
    @get:Rule
    val compose = createComposeRule()

    private val minTarget = 48.dp
    private val MIN_DRAWN = 24.dp
    private val MATERIAL_SHEET_PARTS = setOf("Close sheet", "Drag handle")

    private fun show(content: @Composable () -> Unit) = compose.setContent { CargoClearTheme { content() } }

    private data class Finding(val where: String, val what: String)

    /** What the last audit looked at, so a screen that is audited cannot quietly have nothing on it. */
    private var audited = 0

    private val actionable = androidx.compose.ui.test.SemanticsMatcher("is actionable") {
        it.config.getOrNull(SemanticsActions.OnClick) != null || it.config.getOrNull(SemanticsProperties.ToggleableState) != null ||
            it.config.getOrNull(SemanticsProperties.Selected) != null
    }

    /**
     * Every actionable node on screen, with the problems it has. A control below the fold has no size until it is laid out in view, and one at the edge
     * has only the size of the part that shows, so each is scrolled fully into view first (where something scrolls) and measured after.
     */
    private fun audit(where: String): List<Finding> {
        val density = InstrumentationRegistry.getInstrumentation().targetContext.resources.displayMetrics.density
        val floor = minTarget.value * density
        val minDrawn = MIN_DRAWN.value * density
        val findings = mutableListOf<Finding>()
        val count = compose.onAllNodes(actionable).fetchSemanticsNodes().size
        audited = count
        for (index in 0 until count) {
            val interaction = compose.onAllNodes(actionable)[index]
            // always scrolled to, not only when it has no size: a control cut off by the edge of the screen reports the part that shows
            runCatching { interaction.performScrollTo() }
            val node = interaction.fetchSemanticsNode()
            val config = node.config
            if (config.getOrNull(SemanticsProperties.Disabled) != null && config.getOrNull(SemanticsActions.OnClick) == null) continue
            val text = config.getOrNull(SemanticsProperties.Text)?.joinToString(" ") { it.text }.orEmpty()
            val description = config.getOrNull(SemanticsProperties.ContentDescription)?.joinToString(" ").orEmpty()
            val name = listOf(description, text).filter { it.isNotBlank() }.joinToString(" ").ifBlank { "(no name)" }
            val bounds = node.touchBoundsInRoot
            val label = "${name.take(60)} @ $bounds"
            android.util.Log.i("a11y-audit", "$where | ${name.take(50)} | ${bounds.width / density}x${bounds.height / density} dp | role=${config.getOrNull(SemanticsProperties.Role)}")
            val isTextField = config.getOrNull(SemanticsProperties.EditableText) != null || config.getOrNull(SemanticsActions.SetText) != null
            if (name == "(no name)" && !isTextField) findings += Finding(where, "no name: $label")
            // A text field is announced as an edit box by its text-entry actions, not by a role; the scrim and the handle of a Material bottom sheet are the
            // library's own (named for a screen reader, without a role), and the only controls here that are not this app's.
            if (config.getOrNull(SemanticsProperties.Role) == null && !isTextField && name !in MATERIAL_SHEET_PARTS) findings += Finding(where, "no role: $label")
            val drawn = node.boundsInRoot
            if (bounds.isEmpty || drawn.isEmpty) {
                findings += Finding(where, "could not be brought into view to measure: $label")
            } else {
                if (drawn.width < minDrawn - 1 || drawn.height < minDrawn - 1) {
                    findings += Finding(where, "drawn ${drawn.width / density}x${drawn.height / density} dp (under 24): $label")
                }
                if (bounds.width < floor - 1 || bounds.height < floor - 1) {
                    findings += Finding(where, "touch area ${bounds.width / density}x${bounds.height / density} dp (under 48): $label")
                }
            }
        }
        return findings
    }

    private fun assertClean(where: String, atLeast: Int = 3) {
        compose.waitForIdle()
        val findings = audit(where)
        assertTrue("$where: only $audited controls were audited, expected at least $atLeast", audited >= atLeast)
        assertTrue("accessibility audit of $where:\n" + findings.joinToString("\n") { " - ${it.what}" }, findings.isEmpty())
    }

    private fun bundle(
        state: WorkbenchState,
        correctionsUi: CorrectionsUi = CorrectionsUi(),
        audit: AuditUi = AuditUi(loading = false),
        scan: Boolean = false,
        link: String? = null,
        notify: Boolean = false,
    ): @Composable () -> Unit = {
        BundleContent(
            bundleId = "bnd-test", state = state, appMode = AppMode.DEMO, onBack = {}, onRetry = {}, onSelectDocument = {},
            correctionsUi = correctionsUi, audit = audit, scanAvailable = scan, shareLink = link, notifyOffer = notify,
        )
    }

    // ---- screens

    @Test
    fun home() {
        show {
            HomeContent(
                meta = MetaState.Ready(com.cargoclear.japac.core.model.Meta(AppMode.DEMO, "fixtures")), state = HomeUiState(
                    recents = listOf(RecentBundle("bnd-1", "REF-1", "SG", Status.MISSING_EVIDENCE, 1, 3, 1L)),
                ),
                onRetryMeta = {}, onDestination = {}, onCreateEmpty = {}, onCreateDemo = {}, onOpenText = {}, onOpenTextChanged = {}, onOpenRecent = {}, onForget = {},
            )
        }
        assertClean("home")
    }

    @Test
    fun the_assessment_of_a_bundle_with_corrections() {
        show(bundle(Fixtures.caseDCorrected(), scan = true, link = "https://ui.example.com/workbench/bnd-test", notify = false))
        assertClean("assessment (Case D, corrections pending)")
    }

    @Test
    fun the_assessment_of_a_bundle_that_needs_a_certificate() {
        show(bundle(Fixtures.caseCMissingEvidence()))
        assertClean("assessment (Case C, missing evidence)")
    }

    @Test
    fun the_documents_tab() {
        show(bundle(Fixtures.caseDCorrected()))
        compose.onNodeWithText("Documents").performClick()
        assertClean("documents")
    }

    @Test
    fun the_history_tab_both_segments() {
        show(bundle(Fixtures.caseDRecomputed(), audit = AuditUi(audit = Fixtures.decode("case_d_audit_partial.json"), loading = false)))
        compose.onNodeWithText("History").performClick()
        assertClean("history (Reasoning Delta)")
        compose.onNodeWithText("Audit Chain Timeline").performClick()
        assertClean("history (audit chain)")
    }

    @Test
    fun the_correction_sheet() {
        val state = Fixtures.caseDCorrected()
        val doc = state.documents.first { it.filename == "case_d_mtc_test_cert.pdf" }
        show(bundle(state, correctionsUi = CorrectionsUi().opened(doc.documentId, doc.filename, "test_results[20]", readCell(state.extractions, doc.documentId, "test_results[20]"))))
        assertClean("correction sheet")
    }

    @Test
    fun the_add_document_sheet() {
        show(bundle(Fixtures.caseCMissingEvidence(), scan = true))
        compose.onNodeWithContentDescription("Add document").performClick()
        assertClean("add document sheet")
    }

    @Test
    fun settings_and_about() {
        show { SettingsContent(secure = true, cacheBytes = 1_000_000, onBack = {}, onSecureChange = {}, onClearCache = {}, notify = false, notifyDenied = true) }
        assertClean("settings")
    }

    @Test
    fun about() {
        show { AboutContent(versionName = "0.1.0", licences = "Apache License 2.0 (1 library)\n  androidx (1)", backend = null, onBack = {}) }
        assertClean("about", atLeast = 1) // its one control is Back: the rest is text
    }

    @Test
    fun the_intake_screen() {
        show {
            IntakeContent(
                files = IntakeFiles(listOf(InboxFiles.Imported("file:/x/a.pdf", "a.pdf", 1000)), 0), state = IntakeUi(),
                recent = listOf(RecentBundle("bnd-1", "REF-1", "SG", Status.MISSING_EVIDENCE, 1, 3, 1L)),
                onDestination = {}, onCreate = {}, onAddTo = {}, onBack = {},
            )
        }
        assertClean("intake")
    }

    // ---- the viewer

    private val document = DocumentRecord("d1", "b1", "scan.pdf", "COMMERCIAL_INVOICE", "gs://x", "sha", 1000, "2026-01-01T00:00:00Z", transformMetaUri = "gs://x/t.json")
    private val box = Highlight("H-1", "d1", 1, BBox(1, 300.0, 840.0, 360.0, 930.0), Severity.MATERIAL, "Certificate chemistry contradicts the declared HS code", value = "TH-77121: Cr 0.35%")

    private fun viewer(pages: PdfPages): @Composable () -> Unit = {
        val state = ViewerState().opened(document, listOf(box), 2, fromSavedCopy = false)
            .geometryKnown(listOf(TransformMetadata(page = 1, sourcePage = 1, processedUri = "gs://p/page-001.png")))
            .fileReady(3)
        ViewerContent(
            documentId = "d1", state = state, pages = pages, modelImage = null, onBack = {}, onRetry = {}, onPrevious = {}, onNext = {},
            onSelectBox = {}, onShowModelView = {},
        )
    }

    @Test
    fun the_viewer_and_its_evidence_list() {
        val pages = runBlocking { PdfRendererPages.open(Assets.file("viewer/clean.pdf")) }
        try {
            show(viewer(pages))
            assertClean("viewer", atLeast = 6)
            compose.onNodeWithText("Evidence (1)").performClick()
            assertClean("viewer evidence list", atLeast = 6)
        } finally {
            pages.close()
        }
    }
}
