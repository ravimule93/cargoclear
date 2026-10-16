"""pytest configuration and shared hermetic test fixtures."""

import os

import pytest

# Test modules whose uploads are placeholder bytes ("%PDF-1.4 invoice"): they predate the poppler-based upload checks and the rule
# that a file poppler cannot render is never passed on raw. They were written to pass on a machine WITHOUT poppler (a placeholder is
# not renderable), and for these modules that is what they get: pdfinfo reports "not installed", the upload checks are skipped and
# preprocessing passes the bytes through. A module leaves this list when its placeholders become real PDFs; a single test can leave it
# with @pytest.mark.real_poppler, or join it with @pytest.mark.placeholder_pdfs. Everything else, including tests/gating, gets the real checks.
PLACEHOLDER_PDF_MODULES = frozenset({
    "test_run_lifecycle", "test_path_ids", "test_run_leases", "test_run_cap", "test_audit_lifecycle", "test_data_source",
    "test_engines", "test_stream", "test_signing", "test_run_events", "test_rate_limit", "test_orchestrator",
    "test_live_mode_integrity", "test_internal_worker", "test_storage", "test_iterations_route", "test_demo", "test_body_limits",
    "test_pipeline_pages", "test_documents_api",
})


@pytest.fixture(autouse=True)
def placeholder_pdfs_see_no_poppler(request, monkeypatch):
    """See ``PLACEHOLDER_PDF_MODULES``: for those tests poppler's pdfinfo is reported as not installed."""
    wanted = request.module.__name__.rsplit(".", 1)[-1] in PLACEHOLDER_PDF_MODULES or request.node.get_closest_marker("placeholder_pdfs")
    if not wanted or request.node.get_closest_marker("real_poppler"):
        return
    from pdf2image.exceptions import PDFInfoNotInstalledError

    def not_installed(*_args, **_kwargs):
        raise PDFInfoNotInstalledError("poppler is reported as not installed for tests that upload placeholder PDFs")

    monkeypatch.setattr("pdf2image.pdf2image.pdfinfo_from_path", not_installed)
    from app.services import upload_checks

    monkeypatch.setattr(upload_checks, "embedded_file_count", lambda _data: None)  # pdfdetach is part of the same poppler


@pytest.fixture(autouse=True)
def hermetic_test_env(tmp_path, monkeypatch):
    """Hermetic test environment fixture.

    Enforces:
      (a) Deletes GOOGLE_APPLICATION_CREDENTIALS and K_SERVICE (and undoes any export app.core.mode makes), resets
          settings.google_application_credentials to None, and forces the gcloud ADC-file detection
          (app.core.mode._adc_file_exists) to False.
      (b) Sets APP_MODE=demo.
      (c) Points LOCAL_STORAGE_PATH at a fresh tmp_path.
      (d) Clears all in-memory stores in firestore.py and audit.py, the SSE wake-up channels and the rate limiter.

    The shared ``settings`` singleton is patched through ``monkeypatch.setattr`` so the original
    ``app_mode`` / ``local_storage_path`` are restored after every test, whatever a test did to them.
    """
    # Registering the variables with monkeypatch BEFORE deleting them makes monkeypatch restore the original state
    # (absent) at teardown, even if app.core.mode exports GOOGLE_APPLICATION_CREDENTIALS during the test: a bare
    # delenv(raising=False) on an absent variable records nothing, and the export would leak into later tests.
    for name in ("GOOGLE_APPLICATION_CREDENTIALS", "K_SERVICE"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    # A developer's real `gcloud auth application-default login` file must never make a test live.
    from app.core import mode

    monkeypatch.setattr(mode, "_adc_file_exists", lambda: False)
    monkeypatch.setenv("APP_MODE", "demo")
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path))

    from app.core.config import settings

    monkeypatch.setattr(settings, "app_mode", "demo")
    monkeypatch.setattr(settings, "local_storage_path", str(tmp_path))
    monkeypatch.setattr(settings, "google_application_credentials", None)  # never the developer's .env value
    # Audit signing appends an event to every bundle's chain: the tests of everything else assert exact event sequences, so
    # it is off unless a test (tests/unit/test_signing.py) turns it on.
    monkeypatch.setattr(settings, "audit_signing", False)
    monkeypatch.setattr(settings, "signing_key_version", None)
    # The pipeline engine comes from the PROCESS environment only (the ADK run sets PIPELINE_ENGINE=adk for the whole suite);
    # a developer's .env must not decide which engine the tests exercise.
    monkeypatch.setattr(settings, "pipeline_engine", os.environ.get("PIPELINE_ENGINE", "native"))

    # Reset Firestore in-memory state
    from app.repo import firestore

    firestore._IN_MEMORY_BUNDLES.clear()
    firestore._IN_MEMORY_DOCS.clear()
    firestore._IN_MEMORY_RUNS.clear()
    firestore._IN_MEMORY_ITERATIONS.clear()
    firestore._IN_MEMORY_EXTRACTIONS.clear()
    firestore._IN_MEMORY_EXTRACTION_CACHE.clear()
    firestore._IN_MEMORY_USAGE.clear()
    firestore._IN_MEMORY_DAILY_TOKENS.clear()
    firestore._firestore_client = None

    # Reset Audit in-memory state
    from app.services import audit

    audit._IN_MEMORY_AUDIT.clear()
    audit._firestore_client = None

    # Reset the run leases (demo-mode store and the cached client)
    from app.repo import leases

    leases.reset_for_tests()
    from app.services import orchestrator

    orchestrator._SHUTTING_DOWN = False
    from app.services import signing

    signing.reset_for_tests()

    # Reset Extraction client
    from app.agents import extraction

    extraction._genai_client = None

    # Reset the SSE wake-up channels (a subscription some test left open must not leak into the next one)
    from app.services import run_events

    run_events._CHANNELS.clear()

    # Reset the rate limiter: the whole suite posts far more than 60 writes a minute from one test client
    from app.gateway import limits

    limits.rate_limiter.reset()

    yield


@pytest.fixture
def sample_extracted_document():
    """A valid ExtractedDocument for use in unit tests."""
    from app.domain.schemas import (
        ExtractedDocument, FieldRef, LineItem, BBox
    )

    def ref(v, c=0.97):
        return FieldRef(
            value=v, confidence=c,
            bbox=BBox(page=1, ymin=100, xmin=50, ymax=150, xmax=500)
        )

    return ExtractedDocument(
        document_id="test-doc-001",
        doc_type="PACKING_LIST",
        doc_type_confidence=0.99,
        consignee=ref("SINGAPORE TRADING PTE LTD"),
        consignor=ref("MUMBAI STEEL WORKS LTD"),
        total_net_weight_kg=ref(14000.0),
        total_gross_weight_kg=ref(14280.0),
        tare_weight_kg=ref(280.0),
        line_items=[
            LineItem(
                description=ref("Steel pipes for industrial use"),
                quantity=ref("100 PCS"),
                net_weight_kg=ref(14000.0),
                gross_weight_kg=ref(14280.0),
                hs_code_declared=ref("73041900"),
            )
        ],
    )


@pytest.fixture
def sample_bol_document():
    """A sample Bill of Lading document."""
    from app.domain.schemas import ExtractedDocument, FieldRef, BBox

    def ref(v, c=0.97):
        return FieldRef(
            value=v, confidence=c,
            bbox=BBox(page=1, ymin=100, xmin=50, ymax=150, xmax=500)
        )

    return ExtractedDocument(
        document_id="test-bol-001",
        doc_type="BILL_OF_LADING",
        doc_type_confidence=0.99,
        consignee=ref("SINGAPORE TRADING PTE LTD"),
        consignor=ref("MUMBAI STEEL WORKS LTD"),
        total_gross_weight_kg=ref(14280.0),
    )
