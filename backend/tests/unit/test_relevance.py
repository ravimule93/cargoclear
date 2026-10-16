"""services/relevance.py: what a first page says it is (the text layer), which pages are read, and the vision gate's decisions.

No Gemini, no credentials: the model is a fake client, and ``pdftotext`` is faked where a test is about its failure modes. The
checks against real files (the gating fixtures) skip on a machine without poppler.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from app.core.config import Settings, settings
from app.gateway.errors import ValidationError
from app.services import relevance
from tests.helpers import REPO_ROOT

GATING = REPO_ROOT / "backend" / "tests" / "fixtures" / "gating"
needs_poppler = pytest.mark.skipif(shutil.which("pdftotext") is None, reason="poppler (pdftotext) is not installed")

TERMS = "\n".join(f"{n}.{m}  The Buyer shall inspect the goods on arrival and notify the Seller of any defect." for n in (1, 2) for m in range(1, 21))
TABLE = "\n".join(f"{n:05d}  SEAMLESS PIPE 73043100  {n % 9}.{n % 997:03d} MT  {640 + n % 90}.{n % 100:02d} USD  HEAT H{n:06d}" for n in range(1, 41))


# --- what a first page says it is ---


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("COMMERCIAL   INVOICE\nNo. 1", "COMMERCIAL_INVOICE"),
        ("  bill of lading  ", "BILL_OF_LADING"),
        ("PACKING LIST", "PACKING_LIST"),
        ("Mill Test Certificate EN 10204 3.1", "MILL_TEST_CERTIFICATE"),
        ("Certificate of Origin", "CERTIFICATE_OF_ORIGIN"),
        ("商业发票 发票号码", "COMMERCIAL_INVOICE"),
        ("Shipper: A  Vessel: B  Port of Loading: C", "BILL_OF_LADING"),  # no title, three field words
    ],
)
def test_a_title_phrase_or_enough_field_words_name_the_document(text, kind) -> None:
    assert relevance.names_a_document(text) == kind
    assert relevance.first_page_verdict(text)[0] == "accept"


def test_two_field_words_are_not_enough_and_the_page_goes_to_the_model() -> None:
    verdict, why = relevance.first_page_verdict("Shipper: A\nVessel: B\nJane Example, software engineer, eight years of experience")

    assert verdict == "vision" and "names no document" in why


@pytest.mark.parametrize("text", ["", "   \n\f ", "12 34"])
def test_a_page_without_a_text_layer_goes_to_the_model_and_says_why(text) -> None:
    verdict, why = relevance.first_page_verdict(text)

    assert verdict == "vision" and "no text layer" in why


def test_the_kinds_are_the_document_types_the_assessment_reads_and_other() -> None:
    assert relevance.KINDS == (
        "COMMERCIAL_INVOICE", "BILL_OF_LADING", "PACKING_LIST", "CERTIFICATE_OF_ORIGIN", "PHYTOSANITARY", "MILL_TEST_CERTIFICATE", "OTHER"
    )


# --- the page plan ---


def test_a_short_document_is_read_whole() -> None:
    plan = relevance.plan_pages(3, ["COMMERCIAL INVOICE", TABLE, TABLE], cap=10)

    assert plan.kept == (1, 2, 3) and plan.boilerplate == () and plan.over_cap == () and plan.basis == "text_layer"


def test_terms_and_conditions_are_skipped_and_clause_numbers_are_not_data() -> None:
    plan = relevance.plan_pages(4, ["COMMERCIAL INVOICE", TERMS, TERMS, TABLE], cap=10)

    assert plan.kept == (1, 4) and plan.boilerplate == (2, 3) and plan.over_cap == ()


def test_page_one_is_always_read_even_when_it_looks_like_boilerplate() -> None:
    plan = relevance.plan_pages(2, [TERMS, TABLE], cap=10)

    assert plan.kept == (1, 2)


def test_a_scanned_page_has_no_text_and_cannot_be_judged_so_it_is_read() -> None:
    plan = relevance.plan_pages(3, ["COMMERCIAL INVOICE", "", TERMS], cap=10)

    assert plan.kept == (1, 2) and plan.boilerplate == (3,)


def test_a_page_that_names_the_document_is_read_without_a_table() -> None:
    plan = relevance.plan_pages(2, ["COMMERCIAL INVOICE", "Packing list\nSee the attached sheet for marks and numbers of packages."], cap=10)

    assert plan.kept == (1, 2)


def test_content_pages_beyond_the_cap_are_not_read_and_are_recorded() -> None:
    plan = relevance.plan_pages(30, [TABLE] * 30, cap=10)

    assert plan.kept == tuple(range(1, 11)) and plan.over_cap == tuple(range(11, 31)) and plan.boilerplate == ()


def test_the_cap_counts_pages_worth_reading_not_pages_of_the_file() -> None:
    plan = relevance.plan_pages(30, ["COMMERCIAL INVOICE"] + [TERMS, TABLE] * 14 + [TERMS], cap=5)

    assert plan.kept == (1, 3, 5, 7, 9) and plan.over_cap == (11, 13, 15, 17, 19, 21, 23, 25, 27, 29) and len(plan.boilerplate) == 15


@pytest.mark.parametrize("texts", [None, [], ["", "", ""], ["  ", "\n"]], ids=["unavailable", "empty-list", "all-empty", "blank"])
def test_without_any_text_the_first_pages_are_taken_and_the_rest_are_recorded(texts) -> None:
    plan = relevance.plan_pages(25, texts, cap=10)

    assert plan.kept == tuple(range(1, 11)) and plan.over_cap == tuple(range(11, 26)) and plan.basis == "no_text_layer"


def test_a_plan_is_json_ready() -> None:
    plan = relevance.plan_pages(4, ["COMMERCIAL INVOICE", TERMS, TERMS, TABLE], cap=10)

    assert json.loads(json.dumps(plan.as_dict())) == {
        "total": 4, "kept": [1, 4], "boilerplate": [2, 3], "over_cap": [], "basis": "text_layer"
    }


@pytest.mark.parametrize(
    ("pages", "text"), [([], ""), ([5], "5"), ([2, 3, 4, 7], "2-4, 7"), ([1, 2], "1-2"), ((11, 12, 13, 14, 15, 30), "11-15, 30")]
)
def test_page_ranges(pages, text) -> None:
    assert relevance.page_ranges(pages) == text


# --- the text layer, by poppler ---


def fake_pdftotext(monkeypatch, *, stdout=b"", returncode=0, raises=None):
    def run(command, **_kw):
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=b"")

    monkeypatch.setattr(relevance.subprocess, "run", run)


def test_pages_are_split_on_the_form_feed_poppler_ends_each_page_with(monkeypatch) -> None:
    fake_pdftotext(monkeypatch, stdout="one\ftwo\f\f".encode())

    assert relevance.read_page_texts(b"%PDF-", 3) == ["one", "two", ""]


@pytest.mark.parametrize(
    "kwargs",
    [{"raises": FileNotFoundError("pdftotext")}, {"raises": subprocess.TimeoutExpired("pdftotext", 15)}, {"stdout": b"", "returncode": 1}],
    ids=["not-installed", "timeout", "nothing-returned"],
)
def test_no_text_can_be_had_is_none_not_an_error(monkeypatch, kwargs) -> None:
    fake_pdftotext(monkeypatch, **kwargs)

    assert relevance.read_page_texts(b"%PDF-", 3) is None


def test_a_page_range_is_asked_for(monkeypatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(relevance.subprocess, "run", lambda command, **_kw: seen.append(command) or subprocess.CompletedProcess(command, 0, b"x\f", b""))

    relevance.read_page_texts(b"%PDF-", 7)

    assert seen[0][:7] == ["pdftotext", "-layout", "-f", "1", "-l", "7", seen[0][6]] and seen[0][-1] == "-"


@needs_poppler
@pytest.mark.real_poppler
@pytest.mark.parametrize(
    ("name", "pages", "kept"),
    [
        ("f01_clean/commercial_invoice.pdf", 1, (1,)), ("f04b_invoice_plus_15_pages_terms.pdf", 16, (1,)),
        ("f04c_invoice_terms_then_table.pdf", 4, (1, 4)), ("f16_worst_case_30_dense_pages.pdf", 30, tuple(range(1, 11))),
        ("f11_scanned_invoice.pdf", 1, (1,)),
    ],
)
def test_real_files_plan_as_the_audit_expects(name, pages, kept) -> None:
    texts = relevance.read_page_texts((GATING / name).read_bytes(), pages)

    assert relevance.plan_pages(pages, texts, cap=10).kept == kept


@needs_poppler
@pytest.mark.real_poppler
def test_a_white_text_sentence_is_in_the_text_layer_and_so_is_never_given_to_a_model() -> None:
    """The reason the text layer only decides: the instruction is in it, and not in the pixels the model is shown."""
    texts = relevance.read_page_texts((GATING / "f06a_white_text_injection.pdf").read_bytes(), 1)

    assert texts is not None and "Ignore previous instructions" in texts[0]


# --- the gate ---


class FakeGateClient:
    """Answers with ``answer``; a list is a script, one entry per request (an exception entry is raised)."""

    def __init__(self, answer: object) -> None:
        self.answer, self.requests = answer, []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _generate(self, **kwargs):
        self.requests.append(kwargs)
        answer = self.answer[len(self.requests) - 1] if isinstance(self.answer, list) else self.answer
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(text=answer)


class Api(Exception):
    """What google-genai raises for an HTTP error: an exception with a ``code``."""

    def __init__(self, code: int) -> None:
        super().__init__(f"HTTP {code}")
        self.code = code


@pytest.fixture
def gate(monkeypatch):
    """The gate with the page text and the page-one image faked, so only its decisions are under test."""
    state = SimpleNamespace(text="Jane Example, software engineer", client=FakeGateClient(json.dumps({"kind": "OTHER"})))
    monkeypatch.setattr(relevance, "read_page_texts", lambda _data, _last: None if state.text is None else [state.text])
    monkeypatch.setattr(relevance, "_first_page_png", lambda _data: b"png")
    state.seen = "same"  # what can be seen on the page: "same" = the page text, None = cannot be worked out, else the words themselves
    monkeypatch.setattr(
        relevance, "visible_first_page_text",
        lambda _data: state.text if state.seen == "same" else state.seen,
    )
    state.sleeps = []

    async def no_wait(seconds):
        state.sleeps.append(seconds)

    monkeypatch.setattr(relevance, "_sleep", no_wait)
    from app.agents import extraction

    monkeypatch.setattr(extraction, "_get_genai_client", lambda: state.client)
    return state


async def test_a_page_that_names_a_document_is_accepted_without_a_request(gate) -> None:
    gate.text = "COMMERCIAL INVOICE"

    await relevance.check_document(b"%PDF-")

    assert gate.client.requests == []


async def test_an_other_answer_refuses_the_file_with_a_message_that_lists_what_is_read(gate) -> None:
    with pytest.raises(ValidationError) as raised:
        await relevance.check_document(b"%PDF-")

    assert raised.value.message == relevance.REJECTION_MESSAGE and raised.value.http_status == 422
    assert raised.value.detail == {"reason": "not_a_shipping_document"}
    [request] = gate.client.requests
    assert request["config"].max_output_tokens == 24 and request["model"] == settings.gemini_live_model
    assert [part.text for part in request["contents"] if getattr(part, "text", None)] == [relevance.GATE_INSTRUCTION]


async def test_a_kind_from_the_list_accepts_the_file(gate) -> None:
    gate.client = FakeGateClient(json.dumps({"kind": "BILL_OF_LADING"}))

    await relevance.check_document(b"%PDF-")


@pytest.mark.parametrize(
    "answer",
    [RuntimeError("Gemini is down"), "not json", json.dumps({"kind": "RECEIPT"}), json.dumps({"other": 1}), json.dumps(["OTHER"])],
    ids=["error", "not-json", "unknown-kind", "no-kind", "wrong-shape"],
)
async def test_a_gate_that_cannot_answer_properly_accepts_the_file(gate, answer) -> None:
    gate.client = FakeGateClient(answer)

    await relevance.check_document(b"%PDF-")  # never refuses for anything but a definite OTHER


@pytest.mark.parametrize("code", [429, 500, 503, 408])
async def test_a_transient_failure_is_tried_once_more_and_the_second_answer_counts(gate, code) -> None:
    gate.client = FakeGateClient([Api(code), json.dumps({"kind": "OTHER"})])

    with pytest.raises(ValidationError):
        await relevance.check_document(b"%PDF-")

    assert len(gate.client.requests) == 2 and len(gate.sleeps) == 1 and 0.5 <= gate.sleeps[0] <= 1.5


async def test_two_transient_failures_in_a_row_accept_the_file_after_two_requests(gate) -> None:
    gate.client = FakeGateClient([Api(429), Api(429), json.dumps({"kind": "OTHER"})])

    await relevance.check_document(b"%PDF-")

    assert len(gate.client.requests) == 2  # never more than one retry


@pytest.mark.parametrize("failure", [Api(400), Api(403), Api(404), RuntimeError("bug")], ids=["400", "403", "404", "other"])
async def test_a_failure_that_will_not_pass_is_not_retried(gate, failure) -> None:
    gate.client = FakeGateClient([failure, json.dumps({"kind": "OTHER"})])

    await relevance.check_document(b"%PDF-")

    assert len(gate.client.requests) == 1 and gate.sleeps == []


async def test_without_a_model_the_file_is_accepted(gate, monkeypatch) -> None:
    from app.agents import extraction

    monkeypatch.setattr(extraction, "_get_genai_client", lambda: None)

    await relevance.check_document(b"%PDF-")


async def test_a_model_that_cannot_even_be_built_is_not_a_refusal(gate, monkeypatch) -> None:
    from app.agents import extraction
    from app.gateway.errors import UpstreamError

    def refuse():
        raise UpstreamError("no credentials")

    monkeypatch.setattr(extraction, "_get_genai_client", refuse)

    await relevance.check_document(b"%PDF-")


async def test_a_page_that_cannot_be_rendered_is_not_a_refusal(gate, monkeypatch) -> None:
    def broken(_data):
        raise RuntimeError("poppler")

    monkeypatch.setattr(relevance, "_first_page_png", broken)

    await relevance.check_document(b"%PDF-")
    assert gate.client.requests == []


async def test_no_text_at_all_goes_to_the_model(gate) -> None:
    gate.text = None

    with pytest.raises(ValidationError):
        await relevance.check_document(b"%PDF-")


async def test_switched_off_nothing_is_asked(gate, monkeypatch) -> None:
    monkeypatch.setattr(settings, "relevance_gate", False)

    await relevance.check_document(b"%PDF-")

    assert gate.client.requests == []


async def test_the_thinking_field_follows_the_setting_like_the_extraction_call(gate, monkeypatch) -> None:
    monkeypatch.setattr(settings, "gemini_thinking_budget", -1)

    with pytest.raises(ValidationError):
        await relevance.check_document(b"%PDF-")

    assert gate.client.requests[0]["config"].thinking_config is None


# --- the settings ---


def test_the_page_settings_have_documented_defaults_and_pages_sent_must_fit_the_request() -> None:
    fresh = Settings(_env_file=None)

    assert (fresh.max_pages_sent, fresh.max_pdf_pages, fresh.gemini_max_pages, fresh.relevance_gate) == (10, 100, 30, True)
    with pytest.raises(ValueError, match="MAX_PAGES_SENT"):
        Settings(_env_file=None, MAX_PAGES_SENT=31)  # type: ignore[call-arg]
    assert Settings(_env_file=None, MAX_PAGES_SENT=30).max_pages_sent == 30  # type: ignore[call-arg]


# --- the text layer is the uploader's: only words that can be SEEN on the page count ---


@needs_poppler
@pytest.mark.parametrize(
    ("name", "text_says", "page_shows"),
    [
        ("f17a_resume_white_title.pdf", "accept", "vision"),         # COMMERCIAL INVOICE in white on the white page
        ("f17b_resume_one_point_title.pdf", "accept", "vision"),     # ... at one point
        ("f17c_resume_visible_title.pdf", "accept", "accept"),       # ... plainly printed: a visible claim is still a claim (see the setting)
        ("f02a_resume_as_invoice.pdf", "vision", "vision"),
        ("f01_clean/commercial_invoice.pdf", "accept", "accept"),
        ("f01_clean/bill_of_lading.pdf", "accept", "accept"),
        ("f01_clean/packing_list.pdf", "accept", "accept"),
        ("f01_clean/mtc_pipe_test_cert.pdf", "accept", "accept"),
        ("f12_non_english_invoice.pdf", "accept", "accept"),         # Chinese text, seen as such
        ("f06a_white_text_injection.pdf", "accept", "accept"),       # the hidden sentence is not the title: the title is visible
        ("f11_scanned_invoice.pdf", "vision", "vision"),             # no text layer at all
    ],
)
def test_a_title_is_trusted_only_when_a_reader_could_see_it(name, text_says, page_shows) -> None:
    data = (GATING / name).read_bytes()
    texts = relevance.read_page_texts(data, 1)
    seen = relevance.visible_first_page_text(data)

    assert relevance.first_page_verdict(texts[0] if texts else "")[0] == text_says
    assert seen is not None and relevance.first_page_verdict(seen)[0] == page_shows


@needs_poppler
def test_the_words_the_reader_cannot_see_are_left_out_of_what_is_seen() -> None:
    seen = relevance.visible_first_page_text((GATING / "f17a_resume_white_title.pdf").read_bytes())

    assert seen is not None and "JANE" in seen and "COMMERCIAL" not in seen and "INVOICE" not in seen


@needs_poppler
async def test_a_resume_that_claims_to_be_an_invoice_in_invisible_text_is_asked_about_and_refused(monkeypatch) -> None:
    from app.agents import extraction

    client = FakeGateClient(json.dumps({"kind": "OTHER"}))
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: client)

    with pytest.raises(ValidationError, match="does not look like"):
        await relevance.check_document((GATING / "f17a_resume_white_title.pdf").read_bytes())

    assert len(client.requests) == 1  # the claim in the text layer did not buy a free pass


@needs_poppler
async def test_a_real_invoice_still_passes_without_a_request(monkeypatch) -> None:
    from app.agents import extraction

    client = FakeGateClient(json.dumps({"kind": "OTHER"}))
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: client)

    assert await relevance.check_document((GATING / "f01_clean" / "commercial_invoice.pdf").read_bytes()) is None
    assert client.requests == []


@needs_poppler
async def test_the_strict_setting_asks_the_model_about_every_new_file(monkeypatch) -> None:
    from app.agents import extraction

    monkeypatch.setattr(settings, "relevance_vision_always", True)
    client = FakeGateClient(json.dumps({"kind": "COMMERCIAL_INVOICE"}))
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: client)

    asked = await relevance.check_document((GATING / "f01_clean" / "commercial_invoice.pdf").read_bytes())

    assert asked is not None and asked.kind == "COMMERCIAL_INVOICE" and len(client.requests) == 1


@needs_poppler
async def test_the_strict_setting_also_catches_a_plainly_printed_claim(monkeypatch) -> None:
    from app.agents import extraction

    monkeypatch.setattr(settings, "relevance_vision_always", True)
    client = FakeGateClient(json.dumps({"kind": "OTHER"}))
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: client)

    with pytest.raises(ValidationError):
        await relevance.check_document((GATING / "f17c_resume_visible_title.pdf").read_bytes())


async def test_text_that_names_a_document_but_cannot_be_checked_against_the_page_goes_to_the_model(gate) -> None:
    gate.text = "COMMERCIAL INVOICE No. 1"
    gate.seen = None  # no render, or no pdftotext -bbox: the claim cannot be checked
    gate.client.answer = json.dumps({"kind": "OTHER"})

    with pytest.raises(ValidationError):
        await relevance.check_document(b"%PDF-")

    assert len(gate.client.requests) == 1
