"""Preprocessing renders only the pages the plan keeps, each under its number in the FILE, and the request labels them that way."""

from __future__ import annotations

import io
import shutil

import pytest
from PIL import Image

from app.agents import extraction
from app.core.config import settings
from app.services import preprocess
from tests.helpers import REPO_ROOT

GATING = REPO_ROOT / "backend" / "tests" / "fixtures" / "gating"
needs_poppler = pytest.mark.skipif(
    shutil.which("pdftoppm") is None or shutil.which("pdftotext") is None, reason="poppler is not installed"
)


def png(seed: int = 0) -> bytes:
    out = io.BytesIO()
    Image.new("L", (30, 40), 255 - seed).save(out, format="PNG")
    return out.getvalue()


def labels(pages: list[dict]) -> tuple[list[str], int | None]:
    from google.genai import types

    parts, count = extraction._build_parts(types, pages)
    return [p.text for p in parts if getattr(p, "text", None) and p.text.startswith("Page ")], count


def test_pages_are_rendered_one_at_a_time_and_only_when_the_loop_asks(monkeypatch) -> None:
    """The memory a document needs is about one page, not all of them: a page is rendered when asked for, and the next is not rendered
    until the loop has moved on (measured: ten pages just under the pixel budget peaked at 2.2 GB together and 0.67 GB one by one)."""
    from app.services.relevance import PagePlan

    asked: list[tuple[int, int]] = []

    def fake(_raw, **kw):
        asked.append((kw["first_page"], kw["last_page"]))
        return [Image.new("L", (10, 10), 255)]

    monkeypatch.setattr("pdf2image.convert_from_path", fake)
    pages = preprocess._render_planned(b"%PDF-", PagePlan(total=9, kept=(1, 2, 3, 7), boilerplate=(), over_cap=(), basis="text_layer"))

    assert asked == []  # nothing is rendered until the first page is asked for
    assert next(pages)[0] == 1 and asked == [(1, 1)]
    assert [page for page, _image in pages] == [2, 3, 7] and asked == [(1, 1), (2, 2), (3, 3), (7, 7)]


@needs_poppler
@pytest.mark.real_poppler
async def test_pages_one_and_four_are_rendered_and_keep_their_page_numbers() -> None:
    result = await preprocess.run({"raw_bytes": (GATING / "f04c_invoice_terms_then_table.pdf").read_bytes(), "document_id": "doc-x"})

    assert [p["source_page"] for p in result["processed_pages"]] == [1, 4] == [p["page"] for p in result["processed_pages"]]
    assert [t["source_page"] for t in result["transform_meta"]] == [1, 4]
    assert [t["processed_page"] for t in result["transform_meta"]] == [1, 2]
    assert result["page_plan"] == {"total": 4, "kept": [1, 4], "boilerplate": [2, 3], "over_cap": [], "basis": "text_layer"}
    assert all(p["total_pages"] == 4 for p in result["processed_pages"])


@needs_poppler
@pytest.mark.real_poppler
async def test_poppler_is_asked_for_those_pages_only(monkeypatch) -> None:
    import pdf2image

    asked: list[tuple[int, int]] = []
    real = pdf2image.convert_from_path

    def spy(path, **kw):
        asked.append((kw.get("first_page"), kw.get("last_page")))
        return real(path, **kw)

    monkeypatch.setattr(pdf2image, "convert_from_path", spy)

    await preprocess.run({"raw_bytes": (GATING / "f04c_invoice_terms_then_table.pdf").read_bytes(), "document_id": "doc-x"})

    assert asked == [(1, 1), (4, 4)]


@needs_poppler
@pytest.mark.real_poppler
async def test_a_30_page_table_is_cut_to_the_cap_and_the_request_says_page_n_of_30() -> None:
    result = await preprocess.run({"raw_bytes": (GATING / "f16_worst_case_30_dense_pages.pdf").read_bytes(), "document_id": "doc-x"})

    assert [p["source_page"] for p in result["processed_pages"]] == list(range(1, settings.max_pages_sent + 1))
    assert result["page_plan"]["over_cap"] == list(range(11, 31))
    texts, count = labels(result["processed_pages"])
    assert texts[0] == "Page 1 of 30." and texts[-1] == "Page 10 of 30." and count == 10


def test_labels_name_the_page_in_the_file_and_the_count_that_bounds_a_box_is_the_highest_page_sent() -> None:
    pages = [{"source_page": 1, "total_pages": 4, "payload": b"a", "mime": "image/png"},
             {"source_page": 4, "total_pages": 4, "payload": b"b", "mime": "image/png"}]

    assert labels(pages) == (["Page 1 of 4.", "Page 4 of 4."], 4)


def test_pages_without_a_total_are_labelled_as_before() -> None:
    pages = [{"page": n, "payload": b"x", "mime": "image/png"} for n in (1, 2, 3)]

    assert labels(pages) == (["Page 1 of 3.", "Page 2 of 3.", "Page 3 of 3."], 3)


def test_the_split_artifacts_find_their_pages_when_the_pages_read_are_not_one_to_n() -> None:
    pages = [{"page": n, "source_page": n, "document_id": "d", "payload": png(n), "mime": "image/png"} for n in (1, 4)]
    transforms = [{"page": n, "source_page": n, "artifact_index": 0, "artifact_page": i, "artifact_id": None, "split_offset": 0}
                  for i, n in enumerate((1, 4), start=1)]

    artifacts = preprocess._split_artifacts(pages, transforms, raw_size=5_000_000, document_id="d")

    assert [a["source_pages"] for a in artifacts] == [[1, 4]]
    assert [(t["source_page"], t["artifact_id"], t["artifact_page"]) for t in transforms] == [(1, "part-001", 1), (4, "part-001", 2)]


async def test_without_a_plan_every_page_is_rendered_as_before(monkeypatch) -> None:
    """No poppler for pdfinfo means no plan (the development-machine case), and a faked renderer's pages are all kept."""
    from app.services import upload_checks

    monkeypatch.setattr(upload_checks, "read_pdf_facts", lambda *_a, **_kw: None)
    monkeypatch.setattr("pdf2image.convert_from_bytes", lambda _raw, **_kw: [Image.new("RGB", (40, 60), "white")] * 3)

    result = await preprocess.run({"raw_bytes": b"%PDF-1.4 x", "document_id": "doc-x"})

    assert [p["source_page"] for p in result["processed_pages"]] == [1, 2, 3] and result["page_plan"] is None
    assert all("total_pages" not in p for p in result["processed_pages"])


async def test_a_file_pdfinfo_cannot_open_fails_the_document_it_is_not_rendered_without_a_cap(monkeypatch) -> None:
    """Placeholder bytes pdfinfo cannot read: no cap and no pixel budget could be applied, so nothing is rendered (a renderer that would
    happily return 100 pages is never asked) and the document fails with the reason."""
    from app.gateway.errors import PipelineError

    asked: list[str] = []
    monkeypatch.setattr("pdf2image.convert_from_bytes", lambda _raw, **_kw: asked.append("bytes") or [Image.new("RGB", (40, 60), "white")] * 100)
    monkeypatch.setattr("pdf2image.convert_from_path", lambda _path, **_kw: asked.append("path") or [Image.new("RGB", (40, 60), "white")] * 100)

    with pytest.raises(PipelineError, match="could not be rendered .PdfUnreadable"):
        await preprocess.run({"raw_bytes": b"%PDF-1.4 x", "document_id": "doc-x"})

    assert asked == []


def test_the_bytes_are_written_to_disk_once_for_all_the_pages_and_the_text(monkeypatch) -> None:
    """One temporary file for the plan's text and every page render (convert_from_bytes wrote the whole PDF again for each page)."""
    import tempfile

    from app.services import upload_checks
    from app.services.relevance import PagePlan

    opened: list[str] = []
    real = tempfile.NamedTemporaryFile

    def counting(*args, **kwargs):
        handle = real(*args, **kwargs)
        opened.append(handle.name)
        return handle

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", counting)
    seen_paths: list[str] = []
    monkeypatch.setattr("pdf2image.convert_from_path", lambda path, **_kw: seen_paths.append(path) or [Image.new("L", (10, 10), 255)])
    raw = b"%PDF-1.4 x"

    with upload_checks.shared_pdf(raw):
        list(preprocess._render_planned(raw, PagePlan(total=5, kept=(1, 2, 3, 4, 5), boilerplate=(), over_cap=(), basis="text_layer")))

    assert len(opened) == 1 and seen_paths == opened * 5
