package com.cargoclear.japac.ui.history

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import com.cargoclear.japac.Fixtures
import com.cargoclear.japac.core.model.AssessmentIteration
import com.cargoclear.japac.core.model.AuditResponse
import com.cargoclear.japac.ui.theme.CargoClearTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** The History tab: the Reasoning Delta as cards, and the audit chain with its signature. */
class HistoryContentTest {
    @get:Rule
    val compose = createComposeRule()

    private var loads = 0
    private var signs = 0

    private fun show(latest: AssessmentIteration?, audit: AuditUi = AuditUi(loading = false), key: String = "k") {
        compose.setContent {
            CargoClearTheme { HistoryTab(latest = latest, audit = audit, auditRefreshKey = key, onLoadAudit = { loads++ }, onSignNow = { signs++ }) }
        }
    }

    private val recomputed get() = Fixtures.decode<AssessmentIteration>("case_d_assessment_recomputed.json")

    private fun chain(name: String) = AuditUi(audit = Fixtures.decode<AuditResponse>(name), loading = false)

    private fun openAudit() = compose.onNodeWithText("Audit Chain Timeline").performClick()

    // ---- Reasoning Delta

    @Test
    fun the_delta_leads_with_the_narrative_and_shows_every_change_as_a_card() {
        show(recomputed)
        compose.onNodeWithText("Compliance status updated from Material Contradiction to Specialist Review Required", substring = true).assertIsDisplayed()
        compose.onNodeWithText("Status").assertIsDisplayed()
        compose.onNodeWithText("Material Contradiction").assertIsDisplayed()
        compose.onNodeWithText("Specialist Review Required").assertIsDisplayed()
        compose.onNodeWithText("M-001").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("Correction: Certificate cell 21").performScrollTo().assertIsDisplayed()
        compose.onAllNodes(hasText("PREVIOUS STATE", ignoreCase = true)).assertCountEquals(4) // one per change
        compose.onNodeWithText("0.35 %").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("0.28 %").assertIsDisplayed()
    }

    @Test
    fun the_first_assessment_is_a_baseline() {
        show(Fixtures.decode<AssessmentIteration>("case_d_assessment_contradiction.json"))
        compose.onNodeWithText("Baseline Assessment").assertIsDisplayed()
    }

    @Test
    fun with_no_assessment_there_is_nothing_to_compare() {
        show(null)
        compose.onNodeWithText("No assessment iterations available for comparison.").assertIsDisplayed()
    }

    @Test
    fun the_chain_is_not_read_until_its_segment_is_opened() {
        show(recomputed)
        assertEquals(0, loads)
        openAudit()
        compose.waitUntil(timeoutMillis = 2_000) { loads >= 1 }
        assertEquals(1, loads)
    }

    // ---- the audit chain

    @Test
    fun a_chain_that_verifies_and_is_signed_says_so_and_offers_no_signing() {
        show(null, chain("case_d_audit_signed.json"))
        openAudit()
        compose.onNodeWithText("✓ Chain verified").assertIsDisplayed()
        compose.onNodeWithText("✓ Head signed through #7 (demo key, not KMS)").assertIsDisplayed()
        compose.onNodeWithText("Sign now").assertDoesNotExist()
        compose.onNodeWithText("#1 BUNDLE_CREATED").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("Prev: GENESIS").assertIsDisplayed()
    }

    @Test
    fun events_after_the_signed_head_are_said_and_can_be_signed_now() {
        show(null, chain("case_d_audit_partial.json"))
        openAudit()
        compose.onNodeWithText("▲ Signed through #7 (demo key, not KMS); 2 later events not signed yet").assertIsDisplayed()
        compose.onNodeWithText("Sign now").assertIsDisplayed().performClick()
        assertEquals(1, signs)
    }

    @Test
    fun while_signing_the_button_waits() {
        show(null, chain("case_d_audit_partial.json").copy(signing = true))
        openAudit()
        compose.onNodeWithText("Signing...").assertIsNotEnabled()
    }

    @Test
    fun a_refused_signing_is_said_under_the_badge() {
        show(null, chain("case_d_audit_partial.json").copy(signError = "Audit signing is not configured for this service."))
        openAudit()
        compose.onNodeWithText("Audit signing is not configured for this service.").assertIsDisplayed()
    }

    @Test
    fun the_corrections_a_person_made_are_described_in_a_line() {
        show(null, chain("case_d_audit_partial.json"))
        openAudit()
        compose.onNode(hasText("test_results[20] in doc-", substring = true) and hasText("0.35 → 0.28 — the certificate prints 0.28", substring = true)).performScrollTo().assertIsDisplayed()
        compose.onNode(hasText("confirmed as MUMBAI INFRA PIPING PVT LTD", substring = true)).performScrollTo().assertIsDisplayed()
    }

    @Test
    fun what_a_signature_means_is_one_tap_away_in_the_backends_words() {
        show(null, chain("case_d_audit_signed.json"))
        openAudit()
        compose.onNodeWithText("▸ What a signature means here").performClick()
        compose.onNode(hasText("Not legal non-repudiation", substring = true)).assertIsDisplayed()
        compose.onNodeWithText("Key: local-demo").assertIsDisplayed()
    }

    @Test
    fun a_chain_that_does_not_verify_is_never_shown_as_fine() {
        show(null, AuditUi(audit = AuditResponse(verified = false, error = "hash mismatch at #4"), loading = false))
        openAudit()
        compose.onNodeWithText("● Chain BROKEN: hash mismatch at #4").assertIsDisplayed()
    }

    @Test
    fun a_chain_still_loading_says_so_and_a_failure_offers_retry() {
        show(null, AuditUi(loading = true))
        openAudit()
        compose.onNodeWithText("Loading audit chain...").assertIsDisplayed()
    }

    @Test
    fun a_failed_load_says_why_and_retry_loads_again() {
        show(null, AuditUi(loading = false, error = "Can't reach the server. Check your connection and try again."))
        openAudit()
        compose.onNodeWithText("Could not load audit chain: Can't reach the server. Check your connection and try again.").assertIsDisplayed()
        val before = loads
        compose.onNodeWithText("Retry").performClick()
        assertEquals(before + 1, loads)
    }

    @Test
    fun an_empty_chain_says_so() {
        show(null, AuditUi(audit = AuditResponse(verified = true), loading = false))
        openAudit()
        compose.onNodeWithText("No audit events recorded yet.").assertIsDisplayed()
    }
}
