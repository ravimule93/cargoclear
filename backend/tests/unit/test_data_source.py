"""data_source (B4): derived from what actually ran, never from APP_MODE.

extraction sets ctx["extraction_source"] ("fixture" | "live"); grounding sets ctx["grounding_source"]
("seed" | "bigquery"). The iteration is "fixture" if extraction was fixture OR grounding used the seed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.agents import extraction, grounding
from app.agents.extraction import run_extraction_agent
from app.agents.tools import bq_tariff
from app.domain.schemas import BBox, ExtractedDocument, FieldRef, LineItem
from app.gateway import dispatch as dispatch_module
from app.services import orchestrator
from tests.helpers import api_client, create_bundle_with_documents, wait_for_run

FILES = {
    "commercial_invoice.pdf": b"%PDF-1.4 data-source invoice",
    "bill_of_lading.pdf": b"%PDF-1.4 data-source bol",
    "packing_list.pdf": b"%PDF-1.4 data-source packing",
}


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assessment_and_iterations_report_fixture_in_demo_mode() -> None:
    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id))["state"] == "COMPLETE"

        assessment = (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()
        iterations = (await client.get(f"/api/v1/bundles/{bundle_id}/iterations")).json()

    assert assessment["data_source"] == "fixture"
    assert [it["data_source"] for it in iterations] == ["fixture"]


async def _data_source_with_sources(
    monkeypatch: pytest.MonkeyPatch, extraction_source: str, grounding_source: str
) -> str | None:
    """Run the real pipeline but let the extract/ground stages report the given sources."""
    handlers = dispatch_module._get_handlers()
    real_extract, real_ground = handlers["extract"], handlers["ground"]

    async def extract(ctx: dict[str, Any]) -> dict[str, Any]:
        ctx = await real_extract(ctx)
        ctx["extraction_source"] = extraction_source
        return ctx

    async def ground(ctx: dict[str, Any]) -> dict[str, Any]:
        ctx = await real_ground(ctx)
        ctx["grounding_source"] = grounding_source
        return ctx

    monkeypatch.setitem(handlers, "extract", extract)
    monkeypatch.setitem(handlers, "ground", ground)

    async with api_client() as client:
        bundle_id = await create_bundle_with_documents(client, FILES)
        run_id = await orchestrator.start_run(bundle_id)
        assert (await wait_for_run(bundle_id, run_id))["state"] == "COMPLETE"
        return (await client.get(f"/api/v1/bundles/{bundle_id}/assessment")).json()["data_source"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("extraction_source", "grounding_source", "expected"),
    [
        ("live", "bigquery", "live"),
        ("fixture", "bigquery", "fixture"),
        ("live", "seed", "fixture"),
        ("fixture", "seed", "fixture"),
    ],
)
async def test_data_source_follows_what_ran_not_the_app_mode(
    monkeypatch: pytest.MonkeyPatch, extraction_source: str, grounding_source: str, expected: str
) -> None:
    # APP_MODE is "demo" for every case here: only the reported sources may decide the answer.
    assert await _data_source_with_sources(monkeypatch, extraction_source, grounding_source) == expected


def test_derive_data_source_matrix() -> None:
    from app.domain.provenance import derive_data_source

    assert derive_data_source({"extraction_source": "live", "grounding_source": "bigquery"}) == "live"
    assert derive_data_source({"extraction_source": "live", "grounding_source": None}) == "live"
    assert derive_data_source({"extraction_source": "fixture", "grounding_source": "bigquery"}) == "fixture"
    assert derive_data_source({"extraction_source": "live", "grounding_source": "seed"}) == "fixture"
    # nothing reported what ran -> unknown, not a guess from the mode
    assert derive_data_source({}) is None


# ---------------------------------------------------------------------------
# Producers of the two source markers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extraction_marks_fixture_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: None)
    ctx = {"bundle_id": "", "documents": [{"document_id": "d1", "filename": "packing_list.pdf"}]}
    assert (await run_extraction_agent(ctx))["extraction_source"] == "fixture"


@pytest.mark.asyncio
async def test_extraction_marks_live_source_when_gemini_produced_the_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = ExtractedDocument(document_id="ignored", doc_type="PACKING_LIST", doc_type_confidence=0.99)

    async def generate_content(**_kw):  # the async call extraction makes; the answer is read from `.text`
        return SimpleNamespace(text=answer.model_dump_json())

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    monkeypatch.setattr(extraction, "_get_genai_client", lambda: client)
    ctx = {
        "bundle_id": "",
        "documents": [{"document_id": "d1", "filename": "packing_list.pdf"}],
        "processed_pages": [{"document_id": "d1", "page": 1, "payload": b"%PDF", "mime": "application/pdf"}],
    }

    result = await run_extraction_agent(ctx)

    assert result["extraction_source"] == "live"
    assert [d.document_id for d in result["extracted"]] == ["d1"]


def test_lookup_tariff_with_source_reports_seed_offline() -> None:
    hits, source = bq_tariff.lookup_tariff_with_source("Seamless steel pipes for gas pipelines", "SG")
    assert source == "seed"
    assert hits
    assert hits[0]["hs_code"]


def test_lookup_tariff_keeps_its_signature_and_returns_only_hits() -> None:
    hits = bq_tariff.lookup_tariff("Seamless steel pipes for gas pipelines", destination_country="SG")
    expected, _ = bq_tariff.lookup_tariff_with_source("Seamless steel pipes for gas pipelines", "SG")
    assert isinstance(hits, list)
    assert hits == expected


def test_lookup_tariff_with_source_reports_bigquery_when_the_client_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {"hs_code": "73041900", "description": "pipe", "required_documents": [], "distance": 0.05}
    job = SimpleNamespace(result=lambda timeout=None: [row])
    monkeypatch.setattr(bq_tariff, "_get_bq_client", lambda: SimpleNamespace(query=lambda *_a, **_k: job))

    hits, source = bq_tariff.lookup_tariff_with_source("pipe", "SG")

    assert source == "bigquery"
    assert len(hits) == 1
    assert {k: hits[0][k] for k in row} == row  # the row's own columns are returned unchanged
    assert hits[0]["rule_set"] == "demo-curated"  # plus the provenance columns (defaulted: this row has none)


def test_lookup_falls_back_to_seed_in_demo_when_bigquery_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("bq down")

    monkeypatch.setattr(bq_tariff, "_get_bq_client", lambda: SimpleNamespace(query=boom))
    hits, source = bq_tariff.lookup_tariff_with_source("Seamless steel pipes for gas pipelines", "SG")
    assert source == "seed"
    assert hits


def _ref(value: Any) -> FieldRef:
    return FieldRef(value=value, confidence=0.98, bbox=BBox(page=1, ymin=0, xmin=0, ymax=10, xmax=10))


def _invoice() -> ExtractedDocument:
    return ExtractedDocument(
        document_id="doc-inv",
        doc_type="COMMERCIAL_INVOICE",
        doc_type_confidence=0.99,
        line_items=[
            LineItem(
                description=_ref("Line pipe seamless steel for oil pipelines"),
                quantity=_ref("1"),
                net_weight_kg=_ref(1.0),
                gross_weight_kg=_ref(1.0),
                hs_code_declared=_ref("73041900"),
            )
        ],
    )


@pytest.mark.asyncio
async def test_grounding_marks_seed_source_offline() -> None:
    result = await grounding.run_grounding_agent({"extracted": [_invoice()], "destination_country": "SG"})
    assert result["grounding_source"] == "seed"


@pytest.mark.asyncio
async def test_grounding_marks_bigquery_when_every_lookup_came_from_bigquery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hit = {"hs_code": "73041900", "description": "pipe", "required_documents": [], "distance": 0.05}
    monkeypatch.setattr(grounding, "lookup_tariff_with_source", lambda *_a, **_k: ([hit], "bigquery"))
    result = await grounding.run_grounding_agent({"extracted": [_invoice()], "destination_country": "SG"})
    assert result["grounding_source"] == "bigquery"


@pytest.mark.asyncio
async def test_grounding_source_is_seed_if_any_lookup_used_the_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    hit = {"hs_code": "73041900", "description": "pipe", "required_documents": [], "distance": 0.05}

    def lookup(description: str, destination_country: str = "SG"):
        # two DIFFERENT descriptions, so two lookups happen (an identical description is looked up once)
        return ([hit], "seed" if "wheat" in description.lower() else "bigquery")

    monkeypatch.setattr(grounding, "lookup_tariff_with_source", lookup)
    second = _invoice().model_copy(deep=True, update={"document_id": "doc-inv-2"})
    second.line_items[0].description = _ref("Wheat grains for human consumption")
    result = await grounding.run_grounding_agent({"extracted": [_invoice(), second], "destination_country": "SG"})
    assert result["grounding_source"] == "seed"


@pytest.mark.asyncio
async def test_grounding_source_is_none_when_no_tariff_lookup_ran() -> None:
    doc = ExtractedDocument(document_id="d", doc_type="BILL_OF_LADING", doc_type_confidence=0.9)
    result = await grounding.run_grounding_agent({"extracted": [doc], "destination_country": "SG"})
    assert result["grounding_source"] is None
