"""classify_filename: the offline demo classifies documents purely from filename tokens."""

import pytest

from app.agents.extraction import classify_filename


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("commercial_invoice.pdf", "COMMERCIAL_INVOICE"),
        ("Commercial_Invoice_INV-2024-001.pdf", "COMMERCIAL_INVOICE"),
        ("invoice.pdf", "COMMERCIAL_INVOICE"),
        ("bill_of_lading.pdf", "BILL_OF_LADING"),
        ("Bill_of_Lading_BL-8941.pdf", "BILL_OF_LADING"),
        ("bol.pdf", "BILL_OF_LADING"),
        ("packing_list.pdf", "PACKING_LIST"),
        ("Packing_List_PL-001.pdf", "PACKING_LIST"),
        ("PL.pdf", "PACKING_LIST"),
        ("mtc_pipe_test_cert.pdf", "MILL_TEST_CERTIFICATE"),
        ("mtc-pipe-test-cert.pdf", "MILL_TEST_CERTIFICATE"),
        # Tokens must match whole words: "test"/"contest"/"simple" must not classify anything.
        ("sample.pdf", "UNKNOWN"),
        ("example.pdf", "UNKNOWN"),
        ("simple-test.pdf", "UNKNOWN"),
        ("contest-results.pdf", "UNKNOWN"),
    ],
)
def test_classify_filename_matrix(filename: str, expected: str) -> None:
    assert classify_filename(filename) == expected
