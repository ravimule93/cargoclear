"""services/upload_checks.py: pure checks on an uploaded file and its name (C2, C3, C4)."""

from __future__ import annotations

import pytest

from app.gateway.errors import ValidationError
from app.services import upload_checks as checks

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


# ---------------------------------------------------------------------------
# C2: content checks
# ---------------------------------------------------------------------------


def test_a_pdf_header_within_the_first_1024_bytes_is_accepted() -> None:
    checks.check_pdf_header(PDF)
    checks.check_pdf_header(b"\xef\xbb\xbf" + PDF)  # a byte-order mark before the header
    checks.check_pdf_header(b"x" * 1019 + b"%PDF-")  # the header ends exactly at byte 1024


@pytest.mark.parametrize(
    "data",
    [b"MZ\x90\x00\x03", b"PK\x03\x04", b"hello", b"%PDF", b"%pdf-1.4", b"x" * 1020 + b"%PDF-", b"<html>%PD</html>"],
    ids=["exe", "zip", "text", "short-magic", "lowercase", "header-after-1024", "html"],
)
def test_anything_else_is_not_a_pdf(data) -> None:
    with pytest.raises(ValidationError) as raised:
        checks.check_pdf_header(data)

    assert raised.value.message == "The file is not a PDF." and raised.value.http_status == 422


def test_an_encrypted_pdf_is_refused() -> None:
    with pytest.raises(ValidationError) as raised:
        checks.check_not_encrypted(PDF + b"\ntrailer << /Root 1 0 R /Encrypt 5 0 R >>")

    assert raised.value.message == "Password-protected PDFs are not supported."


def test_an_unencrypted_pdf_passes_the_encryption_check() -> None:
    checks.check_not_encrypted(PDF)


def test_the_page_limit_message_names_both_numbers() -> None:
    with pytest.raises(ValidationError) as raised:
        checks.check_page_limit(31, 30)

    assert raised.value.message == "The document has 31 pages; the limit is 30."
    checks.check_page_limit(30, 30)
    checks.check_page_limit(1, 30)


def test_an_unknown_page_count_skips_the_limit() -> None:
    checks.check_page_limit(None, 30)


def test_the_page_count_comes_from_pdfinfo(monkeypatch) -> None:
    monkeypatch.setattr("pdf2image.pdfinfo_from_bytes", lambda data, **_kw: {"Pages": 7})

    assert checks.pdf_page_count(PDF) == 7


def test_the_page_count_is_none_when_poppler_is_missing(monkeypatch) -> None:
    from structlog.testing import capture_logs

    def missing(_data, **_kw):
        raise RuntimeError("Unable to get page count. Is poppler installed and in PATH?")

    monkeypatch.setattr("pdf2image.pdfinfo_from_bytes", missing)
    with capture_logs() as logs:
        assert checks.pdf_page_count(PDF) is None

    skipped = [entry for entry in logs if entry["event"] == "pdf_page_count_skipped"]
    assert len(skipped) == 1 and skipped[0]["log_level"] == "info"


def test_the_page_count_is_none_when_pdfinfo_fails_on_a_broken_pdf(monkeypatch) -> None:
    def broken(_data, **_kw):
        raise ValueError("Syntax Error: Couldn't find trailer dictionary")

    monkeypatch.setattr("pdf2image.pdfinfo_from_bytes", broken)

    assert checks.pdf_page_count(b"%PDF-1.4 truncated") is None


def test_a_pdfinfo_answer_without_pages_is_none(monkeypatch) -> None:
    monkeypatch.setattr("pdf2image.pdfinfo_from_bytes", lambda data, **_kw: {"Title": "x"})

    assert checks.pdf_page_count(PDF) is None


def test_check_pdf_runs_the_checks_in_order(monkeypatch) -> None:
    monkeypatch.setattr("pdf2image.pdfinfo_from_bytes", lambda data, **_kw: {"Pages": 99})

    with pytest.raises(ValidationError, match="not a PDF"):
        checks.check_pdf(b"MZ" + b"/Encrypt", max_pages=30)
    with pytest.raises(ValidationError, match="Password-protected"):
        checks.check_pdf(PDF + b"/Encrypt", max_pages=30)
    with pytest.raises(ValidationError, match="The document has 99 pages; the limit is 30."):
        checks.check_pdf(PDF, max_pages=30)


def test_check_pdf_accepts_a_good_pdf_when_poppler_is_unavailable(monkeypatch) -> None:
    def missing(_data, **_kw):
        raise RuntimeError("no poppler")

    monkeypatch.setattr("pdf2image.pdfinfo_from_bytes", missing)

    checks.check_pdf(PDF, max_pages=30)


def test_the_case_c_pdfs_are_accepted() -> None:
    from tests.helpers import CASE_C_DIR

    for path in sorted(CASE_C_DIR.glob("*.pdf")):
        checks.check_pdf(path.read_bytes(), max_pages=30)


# ---------------------------------------------------------------------------
# C3: file names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("invoice.pdf", "invoice.pdf"),
        ("发票.pdf", "发票.pdf"),
        ("Rechnung für März.pdf", "Rechnung für März.pdf"),
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\bob\\evil.pdf", "evil.pdf"),
        ("a/b\\c/d.pdf", "d.pdf"),
        ("evil\r\nname.pdf", "evilname.pdf"),
        ('say "hi".pdf', "say hi.pdf"),
        ("it's.pdf", "its.pdf"),
        ("  many   spaces \t here.pdf  ", "many spaces here.pdf"),
        ("nul\x00byte.pdf", "nulbyte.pdf"),
        ("bidi\u202egnp.pdf", "bidignp.pdf"),
        ("a\u200bb.pdf", "ab.pdf"),
    ],
    ids=["plain", "chinese", "umlauts", "traversal", "windows", "mixed-separators", "crlf", "double-quotes", "apostrophe",
         "whitespace", "nul", "bidi-override", "zero-width"],
)
def test_sanitize_filename(raw, expected) -> None:
    assert checks.sanitize_filename(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", ".", "..", "...", "/", "\\", "a/", "../..", '""', "\r\n", "\x00"])
def test_a_name_with_nothing_usable_falls_back(raw) -> None:
    assert checks.sanitize_filename(raw) == "document.pdf"


def test_a_400_character_name_is_cut_to_150_and_keeps_its_extension() -> None:
    name = checks.sanitize_filename("a" * 396 + ".pdf")

    assert len(name) == 150 and name.endswith(".pdf") and name == "a" * 146 + ".pdf"


def test_a_name_of_exactly_150_characters_is_untouched() -> None:
    raw = "b" * 146 + ".pdf"

    assert checks.sanitize_filename(raw) == raw


def test_a_long_name_with_a_long_fake_extension_is_still_cut_to_150() -> None:
    name = checks.sanitize_filename("x." + "e" * 400)

    assert len(name) == 150


def test_a_long_unicode_name_is_cut_by_characters_not_bytes() -> None:
    name = checks.sanitize_filename("发" * 300 + ".pdf")

    assert len(name) == 150 and name.endswith(".pdf") and name.startswith("发")


def test_sanitising_is_idempotent() -> None:
    for raw in ("../../etc/passwd.pdf", "发票.pdf", "a" * 400 + ".pdf", 'q"uo\r\nte.pdf'):
        once = checks.sanitize_filename(raw)
        assert checks.sanitize_filename(once) == once


# ---------------------------------------------------------------------------
# C4: download headers
# ---------------------------------------------------------------------------


def test_content_disposition_for_an_ascii_name() -> None:
    assert checks.content_disposition("invoice.pdf") == "inline; filename=\"invoice.pdf\"; filename*=UTF-8''invoice.pdf"


def test_content_disposition_for_a_chinese_name() -> None:
    value = checks.content_disposition("发票.pdf")

    assert value == "inline; filename=\"__.pdf\"; filename*=UTF-8''%E5%8F%91%E7%A5%A8.pdf"
    value.encode("latin-1")  # must not raise: this is what Starlette does with a header value


def test_content_disposition_cannot_be_broken_out_of_by_a_hostile_stored_name() -> None:
    value = checks.content_disposition('x".pdf\r\nSet-Cookie: a=b; \\ %41')

    value.encode("ascii")
    assert "\r" not in value and "\n" not in value
    fallback = value.split('filename="', 1)[1].split('"; filename*', 1)[0]
    assert '"' not in fallback and "\\" not in fallback and "%" not in fallback
    assert "Set-Cookie" in fallback or "Set_Cookie" in fallback  # harmless text inside the quoted string


def test_download_headers() -> None:
    headers = checks.download_headers("发票.pdf")

    assert headers["Content-Disposition"] == checks.content_disposition("发票.pdf")
    assert headers["Cache-Control"] == "private, max-age=3600"
    assert headers["X-Content-Type-Options"] == "nosniff"
