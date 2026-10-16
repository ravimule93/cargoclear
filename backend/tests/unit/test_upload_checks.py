"""services/upload_checks.py: pure checks on an uploaded file and its name (C2, C3, C4)."""

from __future__ import annotations

import shutil

import pytest

from app.gateway.errors import ValidationError
from app.services import upload_checks as checks
from tests.helpers import REPO_ROOT

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


def test_the_page_limit_message_names_both_numbers() -> None:
    with pytest.raises(ValidationError) as raised:
        checks.check_page_limit(31, 30)

    assert raised.value.message == "The document has 31 pages; the limit is 30."
    checks.check_page_limit(30, 30)
    checks.check_page_limit(1, 30)


def test_an_unknown_page_count_skips_the_limit() -> None:
    checks.check_page_limit(None, 30)


# --- what poppler's pdfinfo said (the answers are faked here; the real poppler is exercised against the gating fixtures below) ---


def fake_pdfinfo(monkeypatch, answer):
    """Make ``pdfinfo_from_bytes`` return ``answer`` (a dict) or raise it (an exception); returns the calls it got."""
    calls: list[dict] = []

    def pdfinfo(data, **kw):
        calls.append(kw)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr("pdf2image.pdfinfo_from_bytes", pdfinfo)
    return calls


def test_the_facts_come_from_pdfinfo_and_ask_for_the_first_pages_only(monkeypatch) -> None:
    calls = fake_pdfinfo(monkeypatch, {
        "Pages": 300, "JavaScript": "yes", "Page    1 size": "595.276 x 841.89 pts (A4)", "Page    2 size": "1000 x 2000 pts",
        "Encrypted": "no",
    })

    facts = checks.read_pdf_facts(PDF, max_pages=30)

    assert facts == checks.PdfFacts(pages=300, javascript=True, page_sizes=((1, 595.276, 841.89), (2, 1000.0, 2000.0)))
    assert calls == [{"timeout": 15, "first_page": 1, "last_page": 30}]


def test_a_pdfinfo_answer_with_only_a_page_count_means_no_script_and_no_sizes(monkeypatch) -> None:
    fake_pdfinfo(monkeypatch, {"Pages": 7})

    assert checks.read_pdf_facts(PDF, max_pages=30) == checks.PdfFacts(pages=7, javascript=False, page_sizes=())


def test_a_single_page_size_line_without_a_number_is_page_one(monkeypatch) -> None:
    fake_pdfinfo(monkeypatch, {"Pages": 1, "Page size": "612 x 792 pts (letter)"})

    assert checks.read_pdf_facts(PDF, max_pages=30).page_sizes == ((1, 612.0, 792.0),)


def test_without_poppler_there_are_no_facts_and_the_skip_is_logged(monkeypatch) -> None:
    from pdf2image.exceptions import PDFInfoNotInstalledError
    from structlog.testing import capture_logs

    fake_pdfinfo(monkeypatch, PDFInfoNotInstalledError("Unable to get page count. Is poppler installed and in PATH?"))
    with capture_logs() as logs:
        assert checks.read_pdf_facts(PDF, max_pages=30) is None

    skipped = [entry for entry in logs if entry["event"] == "pdf_checks_skipped"]
    assert len(skipped) == 1 and skipped[0]["reason"] == "poppler_not_installed"


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("Unable to get page count.\nSyntax Error: Couldn't find trailer dictionary"),
        RuntimeError("anything else poppler's wrapper raises"),
        KeyError("Pages"),
    ],
    ids=["broken-pdf", "other-error", "no-page-count"],
)
def test_a_file_poppler_cannot_read_is_unreadable_not_skipped(monkeypatch, failure) -> None:
    fake_pdfinfo(monkeypatch, failure)

    with pytest.raises(checks.PdfUnreadable) as raised:
        checks.read_pdf_facts(PDF, max_pages=30)

    assert not raised.value.password and not raised.value.timed_out


def test_an_answer_without_a_page_count_is_unreadable(monkeypatch) -> None:
    fake_pdfinfo(monkeypatch, {"Title": "x"})

    with pytest.raises(checks.PdfUnreadable):
        checks.read_pdf_facts(PDF, max_pages=30)


def test_poppler_asking_for_a_password_is_a_password_failure(monkeypatch) -> None:
    fake_pdfinfo(monkeypatch, ValueError("Unable to get page count.\nCommand Line Error: Incorrect password"))

    with pytest.raises(checks.PdfUnreadable) as raised:
        checks.read_pdf_facts(PDF, max_pages=30)

    assert raised.value.password


def test_poppler_not_answering_in_time_is_a_timeout(monkeypatch) -> None:
    from pdf2image.exceptions import PDFPopplerTimeoutError

    fake_pdfinfo(monkeypatch, PDFPopplerTimeoutError("Run poppler poppler timeout."))

    with pytest.raises(checks.PdfUnreadable) as raised:
        checks.read_pdf_facts(PDF, max_pages=30)

    assert raised.value.timed_out


# --- page size ---


def test_a_page_at_the_pixel_budget_is_accepted_and_one_over_is_refused() -> None:
    a4 = (1, 595.276, 841.89)
    checks.check_page_sizes((a4,), max_megapixels=4.0)  # A4 at 200 DPI is 3.9 megapixels
    with pytest.raises(ValidationError) as raised:
        checks.check_page_sizes((a4,), max_megapixels=3.8)

    assert raised.value.message == "Page 1 is 595 x 842 points, 4 megapixels when read at 200 DPI; the limit is 3.8."
    assert raised.value.detail == {"page": 1, "megapixels": 4, "max_megapixels": 3.8}


def test_the_page_that_is_too_large_is_named() -> None:
    with pytest.raises(ValidationError, match=r"Page 3 is 3600 x 3600 points, 100 megapixels"):
        checks.check_page_sizes(((1, 595.0, 842.0), (2, 595.0, 842.0), (3, 3600.0, 3600.0)), max_megapixels=50)


# --- check_pdf, with faked answers ---


def test_check_pdf_runs_the_checks_in_order(monkeypatch) -> None:
    fake_pdfinfo(monkeypatch, {"Pages": 99})

    with pytest.raises(ValidationError, match="not a PDF"):
        checks.check_pdf(b"MZ" + b"/Encrypt", max_pages=30)
    with pytest.raises(ValidationError, match="The document has 99 pages; the limit is 30."):
        checks.check_pdf(PDF, max_pages=30)


def test_an_unreadable_file_is_refused_with_a_clear_message(monkeypatch) -> None:
    fake_pdfinfo(monkeypatch, ValueError("Syntax Error: Couldn't find trailer dictionary"))

    with pytest.raises(ValidationError) as raised:
        checks.check_pdf(PDF, max_pages=30)

    assert raised.value.message == "The file could not be read as a PDF." and raised.value.http_status == 422


def test_a_password_protected_file_is_refused_with_the_old_message(monkeypatch) -> None:
    fake_pdfinfo(monkeypatch, ValueError("Command Line Error: Incorrect password"))

    with pytest.raises(ValidationError) as raised:
        checks.check_pdf(PDF, max_pages=30)

    assert raised.value.message == "Password-protected PDFs are not supported."


def test_a_file_poppler_took_too_long_over_is_refused(monkeypatch) -> None:
    from pdf2image.exceptions import PDFPopplerTimeoutError

    fake_pdfinfo(monkeypatch, PDFPopplerTimeoutError("timeout"))

    with pytest.raises(ValidationError, match="took too long"):
        checks.check_pdf(PDF, max_pages=30)


def test_a_file_that_merely_contains_the_word_encrypt_is_not_refused_for_it(monkeypatch) -> None:
    """The old check searched the bytes for /Encrypt; poppler's answer decides now."""
    fake_pdfinfo(monkeypatch, {"Pages": 1, "Encrypted": "yes (print:yes copy:no change:no addNotes:yes algorithm:RC4)"})
    monkeypatch.setattr(checks, "embedded_file_count", lambda _data: 0)

    checks.check_pdf(PDF + b"\ntrailer << /Root 1 0 R /Encrypt 5 0 R >>", max_pages=30)


def test_a_page_too_large_to_render_is_refused(monkeypatch) -> None:
    fake_pdfinfo(monkeypatch, {"Pages": 1, "Page size": "6000 x 6000 pts"})

    with pytest.raises(ValidationError, match="278 megapixels"):
        checks.check_pdf(PDF, max_pages=30, max_page_megapixels=50)


def test_the_pixel_budget_defaults_to_the_setting(monkeypatch) -> None:
    from app.core.config import settings

    fake_pdfinfo(monkeypatch, {"Pages": 1, "Page size": "3600 x 3600 pts"})
    monkeypatch.setattr(checks, "embedded_file_count", lambda _data: 0)
    monkeypatch.setattr(settings, "max_page_megapixels", 200)
    checks.check_pdf(PDF, max_pages=30)  # 100 megapixels, under 200
    monkeypatch.setattr(settings, "max_page_megapixels", 50)
    with pytest.raises(ValidationError, match="100 megapixels"):
        checks.check_pdf(PDF, max_pages=30)


def test_a_file_with_a_script_is_refused(monkeypatch) -> None:
    fake_pdfinfo(monkeypatch, {"Pages": 1, "JavaScript": "yes"})

    with pytest.raises(ValidationError, match="contains scripts"):
        checks.check_pdf(PDF, max_pages=30)


def test_a_file_with_an_attachment_is_refused(monkeypatch) -> None:
    fake_pdfinfo(monkeypatch, {"Pages": 1})
    monkeypatch.setattr(checks, "embedded_file_count", lambda _data: 2)

    with pytest.raises(ValidationError, match="attached or embedded files"):
        checks.check_pdf(PDF, max_pages=30)


def test_check_pdf_accepts_a_good_pdf_when_poppler_is_unavailable(monkeypatch) -> None:
    from pdf2image.exceptions import PDFInfoNotInstalledError

    fake_pdfinfo(monkeypatch, PDFInfoNotInstalledError("no poppler"))
    asked: list[bytes] = []
    monkeypatch.setattr(checks, "embedded_file_count", lambda data: asked.append(data))

    checks.check_pdf(PDF, max_pages=30)

    assert asked == []  # poppler is missing, so pdfdetach is not consulted either


def test_pdfdetach_missing_skips_only_the_attachment_check(monkeypatch) -> None:
    fake_pdfinfo(monkeypatch, {"Pages": 1})

    def missing(*_a, **_kw):
        raise FileNotFoundError("pdfdetach")

    monkeypatch.setattr(checks.subprocess, "run", missing)

    assert checks.embedded_file_count(PDF) is None
    checks.check_pdf(PDF, max_pages=30)


def test_pdfdetach_output_that_is_not_a_count_is_unreadable(monkeypatch) -> None:
    import subprocess

    monkeypatch.setattr(checks.subprocess, "run", lambda *_a, **_kw: subprocess.CompletedProcess([], 1, stdout="", stderr="Error"))

    with pytest.raises(checks.PdfUnreadable):
        checks.embedded_file_count(PDF)


# --- the real poppler, against the audit's fixtures (skipped on a machine without it) ---

GATING = REPO_ROOT / "backend" / "tests" / "fixtures" / "gating"
needs_poppler = pytest.mark.skipif(
    shutil.which("pdfinfo") is None or shutil.which("pdfdetach") is None, reason="poppler (pdfinfo, pdfdetach) is not installed"
)


def gating(name: str) -> bytes:
    return (GATING / name).read_bytes()


@needs_poppler
@pytest.mark.real_poppler
@pytest.mark.parametrize(
    "name",
    [
        "f01_clean/commercial_invoice.pdf", "f01_clean/bill_of_lading.pdf", "f01_clean/packing_list.pdf", "f01_clean/mtc_pipe_test_cert.pdf",
        "f11_scanned_invoice.pdf", "f12_non_english_invoice.pdf", "f04b_invoice_plus_15_pages_terms.pdf", "f16_worst_case_30_dense_pages.pdf",
        "f08b_owner_password_only.pdf", "f05_visible_injection.pdf", "f06a_white_text_injection.pdf", "f06c_metadata_injection.pdf",
    ],
)
def test_real_documents_a_broker_would_upload_are_accepted(name) -> None:
    checks.check_pdf(gating(name), max_pages=30, max_page_megapixels=50)


@needs_poppler
@pytest.mark.real_poppler
@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("f07a_zip_renamed.pdf", "The file is not a PDF."),
        ("f07b_exe_renamed.pdf", "The file is not a PDF."),
        ("f07c_pdf_header_then_zip.pdf", "The file could not be read as a PDF."),
        ("f08a_user_password.pdf", "Password-protected PDFs are not supported."),
        ("f03_300_pages.pdf", "The document has 300 pages; the limit is 30."),
        ("f04a_invoice_plus_40_pages_terms.pdf", "The document has 41 pages; the limit is 30."),
        ("f09_javascript_and_attachment.pdf", "The PDF contains scripts, which are not accepted."),
        ("f09b_javascript_only.pdf", "The PDF contains scripts, which are not accepted."),
        ("f09c_attachment_only.pdf", "The PDF contains attached or embedded files, which are not accepted."),
        ("f10a_huge_page_100mpx.pdf", "Page 1 is 3600 x 3600 points, 100 megapixels when read at 200 DPI; the limit is 50."),
        ("f10b_huge_page_278mpx.pdf", "Page 1 is 6000 x 6000 points, 278 megapixels when read at 200 DPI; the limit is 50."),
        ("f10c_huge_page_1600mpx.pdf", "Page 1 is 14400 x 14400 points, 1600 megapixels when read at 200 DPI; the limit is 50."),
    ],
)
def test_real_hostile_files_are_refused_with_a_message_that_says_why(name, message) -> None:
    with pytest.raises(ValidationError) as raised:
        checks.check_pdf(gating(name), max_pages=30, max_page_megapixels=50)

    assert raised.value.message == message and raised.value.http_status == 422


@needs_poppler
@pytest.mark.real_poppler
def test_a_truncated_real_pdf_is_refused() -> None:
    data = gating("f01_clean/commercial_invoice.pdf")

    with pytest.raises(ValidationError, match="could not be read"):
        checks.check_pdf(data[: len(data) // 2], max_pages=30)


@needs_poppler
@pytest.mark.real_poppler
def test_the_page_limit_is_checked_before_the_sizes_of_pages_beyond_it() -> None:
    """pdfinfo is asked about the first ``max_pages`` pages only, so a long file is refused for its length, not read page by page."""
    with pytest.raises(ValidationError, match="300 pages"):
        checks.check_pdf(gating("f03_300_pages.pdf"), max_pages=30)


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


# ---------------------------------------------------------------------------
# one copy of the file on disk for the poppler tools of a request
# ---------------------------------------------------------------------------


def test_inside_a_shared_block_the_tools_get_one_path_and_outside_each_gets_its_own(monkeypatch) -> None:
    import subprocess
    from types import SimpleNamespace

    from app.services import relevance

    paths: list[str] = []

    def run(command, **_kw):
        paths.append(command[-2] if command[0] == "pdftotext" else command[-1])
        return SimpleNamespace(stdout=b"one\x0c" if command[0] == "pdftotext" else "0 embedded files\n", returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    data = bytes(PDF)

    with checks.shared_pdf(data) as shared:
        assert checks.embedded_file_count(data) == 0 and relevance.read_page_texts(data, 1) == ["one"]
        inside = list(paths)
    checks.embedded_file_count(data)
    relevance.read_page_texts(data, 1)

    assert inside == [shared, shared]
    assert len(set(paths[2:])) == 2 and shared not in paths[2:]


def test_other_bytes_inside_a_shared_block_never_get_the_shared_file(monkeypatch) -> None:
    import subprocess
    from pathlib import Path
    from types import SimpleNamespace

    seen: list[bytes] = []

    def run(command, **_kw):
        seen.append(Path(command[-1]).read_bytes())
        return SimpleNamespace(stdout="0 embedded files\n", returncode=0)

    monkeypatch.setattr(subprocess, "run", run)

    with checks.shared_pdf(bytes(PDF)):
        checks.embedded_file_count(b"%PDF-1.4 some other file")

    assert seen == [b"%PDF-1.4 some other file"]


def test_the_shared_file_is_gone_after_the_block_and_a_thread_started_in_it_sees_it() -> None:
    import asyncio
    from pathlib import Path

    async def inside() -> tuple[str, str]:
        data = bytes(PDF)
        async with checks.shared_pdf_async(data) as path:
            in_thread = await asyncio.to_thread(lambda: checks._SHARED.get()[1])
            assert Path(path).read_bytes() == data
        return path, in_thread

    path, in_thread = asyncio.run(inside())

    assert in_thread == path and not Path(path).exists()
