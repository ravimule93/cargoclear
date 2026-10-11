"""A differential harness: the whole orchestrator, once per engine, on identical inputs, and everything observable compared.

For a scenario it runs ``PIPELINE_ENGINE=native`` and ``PIPELINE_ENGINE=adk`` against fresh in-memory stores and records:

* every persisted iteration (the whole dict; only ``created_at`` is ignored),
* the audit events in order (type, iteration, actor, payload), with run ids and bundle ids replaced by placeholders, and
  whether the hash chain verifies,
* every run-state write in order (stage / terminal state / error, with progress),
* the final run state of every run (minus its timestamp).

``compare(scenario)`` returns the first difference (a path into the recorded structure) or ``None``. Scenarios build their
inputs in code from the Case C PDFs and the ``ExtractedDocument`` objects the offline extractor produces; no new fixtures.
It is used by tests/adk/test_engine_parity.py and, to print the parity matrix, by a one-off script.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.core.config import settings
from app.domain.schemas import ExtractedDocument
from app.gateway import limits
from app.gateway.errors import PipelineError
from app.repo import firestore
from app.services import audit, orchestrator, run_events
from tests.helpers import api_client, case_c_pdf, wait_for_run

PRELOADED = ("commercial_invoice.pdf", "bill_of_lading.pdf", "packing_list.pdf")
MTC = "mtc_pipe_test_cert.pdf"
IGNORED_KEYS = {"created_at", "updated_at", "uploaded_at", "ts", "hash", "prev_hash", "event_id"}


def reset_state() -> None:
    firestore._IN_MEMORY_BUNDLES.clear()
    firestore._IN_MEMORY_DOCS.clear()
    firestore._IN_MEMORY_RUNS.clear()
    firestore._IN_MEMORY_ITERATIONS.clear()
    firestore._IN_MEMORY_EXTRACTIONS.clear()
    audit._IN_MEMORY_AUDIT.clear()
    run_events._CHANNELS.clear()
    limits.rate_limiter.reset()


def case_c_files(*names: str) -> dict[str, bytes]:
    return {name: case_c_pdf(name) for name in names}


class Harness:
    """What a scenario drives. One instance per (scenario, engine) run."""

    def __init__(self, client: Any, mp: pytest.MonkeyPatch) -> None:
        self.client, self.mp = client, mp
        self.bundles: list[str] = []
        self.runs: list[tuple[str, str]] = []  # (bundle_id, run_id), in start order
        self.writes: list[tuple[Any, ...]] = []
        self.mutations: list[Callable[[list[ExtractedDocument]], list[ExtractedDocument]]] = []
        self.fail: dict[str, BaseException] = {}
        self.stall: dict[str, asyncio.Event | float] = {}
        self._install()

    # -- wiring -----------------------------------------------------------------------------------------------------

    def _install(self) -> None:
        from app.gateway import dispatch as dispatch_module

        real_dispatch = orchestrator.dispatch
        handlers = dispatch_module._get_handlers()
        real_extract = handlers["extract"]

        async def extract(ctx: dict[str, Any]) -> dict[str, Any]:
            ctx = await real_extract(ctx)
            docs = list(ctx["extracted"])
            for mutate in self.mutations:
                docs = mutate(docs)
            ctx["extracted"] = docs
            return ctx

        self.mp.setitem(handlers, "extract", extract)

        async def dispatch(stage: str, ctx: dict[str, Any]) -> dict[str, Any]:
            hold = self.stall.get(stage)
            if isinstance(hold, asyncio.Event):
                await hold.wait()
            elif hold:
                await asyncio.sleep(hold)
            if stage in self.fail and ctx.get("raw_bytes") is None:
                raise self.fail[stage]
            return await real_dispatch(stage, ctx)

        self.mp.setattr(orchestrator, "dispatch", dispatch)

        for name in ("set_run_stage", "set_run_state", "set_run_error"):
            self._spy(name)

    def _spy(self, name: str) -> None:
        real = getattr(firestore, name)

        async def spy(bundle_id: str, run_id: str, *args: Any, **kwargs: Any) -> Any:
            if name == "set_run_stage":
                self.writes.append(("stage", kwargs.get("stage", args[0] if args else None), kwargs.get("progress", args[1] if len(args) > 1 else None)))
            elif name == "set_run_state":
                self.writes.append(("state", kwargs.get("state"), kwargs.get("progress"), kwargs.get("only_if_state")))
            else:
                self.writes.append(("error", kwargs.get("error")))
            return await real(bundle_id, run_id, *args, **kwargs)

        self.mp.setattr(firestore, name, spy)

    # -- driving ----------------------------------------------------------------------------------------------------

    async def bundle(self, files: dict[str, bytes], reference: str = "PARITY") -> str:
        created = await self.client.post("/api/v1/bundles", json={"reference": reference, "destination_country": "SG"})
        bundle_id = created.json()["id"]
        self.bundles.append(bundle_id)
        for name, data in files.items():
            await self.upload(bundle_id, name, data)
        return bundle_id

    async def upload(self, bundle_id: str, name: str, data: bytes) -> None:
        response = await self.client.post(
            f"/api/v1/bundles/{bundle_id}/documents", files={"file": (name, data, "application/pdf")}
        )
        assert response.status_code == 201, response.text

    async def start(self, bundle_id: str, mode: str = "full") -> tuple[str, asyncio.Task]:
        before = set(orchestrator._RUNNING_TASKS)
        run_id = await orchestrator.start_run(bundle_id, mode=mode)
        self.runs.append((bundle_id, run_id))
        [task] = set(orchestrator._RUNNING_TASKS) - before
        return run_id, task

    async def run(self, bundle_id: str, mode: str = "full") -> dict[str, Any]:
        run_id, task = await self.start(bundle_id, mode)
        state = await wait_for_run(bundle_id, run_id, timeout=30)
        await asyncio.wait({task}, timeout=10)
        return state

    async def wait_for_stage(self, bundle_id: str, run_id: str, stage: str) -> None:
        for _ in range(2000):
            if (await firestore.get_run_state(bundle_id, run_id)).get("stage") == stage:
                return
            await asyncio.sleep(0.005)
        raise AssertionError(f"run {run_id} never reached {stage}")

    def mutate_documents(self, doc_type: str, change: Callable[[ExtractedDocument], ExtractedDocument]) -> None:
        self.mutations.append(lambda docs: [change(d) if d.doc_type == doc_type else d for d in docs])

    # -- recording --------------------------------------------------------------------------------------------------

    async def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {"writes": [list(w) for w in self.writes], "bundles": [], "runs": []}
        for bundle_id in self.bundles:
            events = await audit.list_audit_events(bundle_id)
            out["bundles"].append({
                "iterations": await firestore.list_iterations(bundle_id),
                "audit": [
                    {k: e[k] for k in ("event_type", "iteration", "actor", "payload")} for e in events
                ],
                "audit_verified": audit.verify_audit_chain(events),
            })
        for bundle_id, run_id in self.runs:
            out["runs"].append(await firestore.get_run_state(bundle_id, run_id))
        return normalise(out, self.bundles, [run_id for _, run_id in self.runs])


def normalise(data: Any, bundle_ids: list[str], run_ids: list[str]) -> Any:
    """Bundle and run ids are random: replace them by placeholders (in the order they were created); drop timestamps."""

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items() if k not in IGNORED_KEYS}
        if isinstance(value, (list, tuple)):
            return [scrub(v) for v in value]
        return value

    text = json.dumps(scrub(data), sort_keys=True, default=str)
    for index, bundle_id in enumerate(bundle_ids):
        text = text.replace(bundle_id, f"<BUNDLE-{index + 1}>")
    for index, run_id in enumerate(run_ids):
        text = text.replace(run_id, f"<RUN-{index + 1}>")
    return json.loads(text)


def first_difference(left: Any, right: Any, path: str = "") -> str | None:
    """The path of the first place two recorded structures differ, with both values; None if they are equal."""
    if type(left) is not type(right):
        return f"{path or '/'}: {left!r} != {right!r}"
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                return f"{path}/{key}: {'missing in native' if key not in left else 'missing in adk'}"
            found = first_difference(left[key], right[key], f"{path}/{key}")
            if found:
                return found
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: native has {len(left)} items, adk has {len(right)}"
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            found = first_difference(a, b, f"{path}[{index}]")
            if found:
                return found
        return None
    return None if left == right else f"{path}: native={left!r} adk={right!r}"


# ---------------------------------------------------------------------------
# scenarios
# ---------------------------------------------------------------------------


async def case_c_iteration_1(h: Harness) -> None:
    bundle_id = await h.bundle(case_c_files(*PRELOADED))
    await h.run(bundle_id)


async def case_c_iteration_2(h: Harness) -> None:
    bundle_id = await h.bundle(case_c_files(*PRELOADED))
    await h.run(bundle_id)
    await h.upload(bundle_id, MTC, case_c_pdf(MTC))
    await h.run(bundle_id, "reassess")


async def weight_mismatch(h: Harness) -> None:
    def heavier(doc: ExtractedDocument) -> ExtractedDocument:
        # the packing list now declares 15,000 net: net + tare no longer matches either its own gross or the Bill of Lading
        net = doc.total_net_weight_kg.model_copy(update={"value": 15000.0})
        return doc.model_copy(update={"total_net_weight_kg": net})

    h.mutate_documents("PACKING_LIST", heavier)
    bundle_id = await h.bundle(case_c_files(*PRELOADED))
    await h.run(bundle_id)


def _with_hs(doc: ExtractedDocument, code: str, header: bool = False) -> ExtractedDocument:
    lines = [li.model_copy(update={"hs_code_declared": li.hs_code_declared.model_copy(update={"value": code})}) for li in doc.line_items]
    update: dict[str, Any] = {"line_items": lines}
    if header and doc.hs_code_header is not None:
        update["hs_code_header"] = doc.hs_code_header.model_copy(update={"value": code})
    return doc.model_copy(update=update)


async def hs_mismatch_invoice_vs_packing_list(h: Harness) -> None:
    h.mutate_documents("PACKING_LIST", lambda d: _with_hs(d, "73062100"))
    bundle_id = await h.bundle(case_c_files(*PRELOADED))
    await h.run(bundle_id)


async def mtc_declares_a_different_hs(h: Harness) -> None:
    h.mutate_documents("MILL_TEST_CERTIFICATE", lambda d: _with_hs(d, "73181500", header=True))
    bundle_id = await h.bundle(case_c_files(*PRELOADED, MTC))
    await h.run(bundle_id)


async def coffee_described_with_the_pipe_code(h: Harness) -> None:
    def coffee(doc: ExtractedDocument) -> ExtractedDocument:
        lines = [li.model_copy(update={"description": li.description.model_copy(update={"value": "Arabica coffee beans, green, unroasted"})}) for li in doc.line_items]
        return doc.model_copy(update={"line_items": lines})

    h.mutate_documents("COMMERCIAL_INVOICE", coffee)
    bundle_id = await h.bundle(case_c_files(*PRELOADED))
    await h.run(bundle_id)


async def duplicate_documents(h: Harness) -> None:
    files = case_c_files(*PRELOADED)
    files["commercial_invoice_copy.pdf"] = case_c_pdf("commercial_invoice.pdf") + b"\n% a second copy of the invoice\n"
    bundle_id = await h.bundle(files)
    await h.run(bundle_id)


async def an_unknown_document(h: Harness) -> None:
    files = case_c_files(*PRELOADED)
    files["scan_0001.pdf"] = b"%PDF-1.4 something nobody can classify\n"
    bundle_id = await h.bundle(files)
    await h.run(bundle_id)


async def a_low_confidence_field(h: Harness) -> None:
    def blurry(doc: ExtractedDocument) -> ExtractedDocument:
        return doc.model_copy(update={"consignee": doc.consignee.model_copy(update={"confidence": 0.80})})  # 0.65-0.94

    h.mutate_documents("BILL_OF_LADING", blurry)
    bundle_id = await h.bundle(case_c_files(*PRELOADED))
    await h.run(bundle_id)


async def a_stage_raises_an_unexpected_error(h: Harness) -> None:
    h.fail["ground"] = RuntimeError("TOP-SECRET /Users/someone/key.json")
    bundle_id = await h.bundle(case_c_files(*PRELOADED))
    await h.run(bundle_id)


async def a_stage_raises_a_domain_error(h: Harness) -> None:
    h.fail["ground"] = PipelineError("the tariff lookup could not be completed", detail={"stage": "ground"})
    bundle_id = await h.bundle(case_c_files(*PRELOADED))
    await h.run(bundle_id)


async def the_deadline_expires(h: Harness) -> None:
    h.mp.setattr(settings, "run_timeout_seconds", 0.4)
    h.stall["extract"] = 30
    bundle_id = await h.bundle(case_c_files(*PRELOADED))
    await h.run(bundle_id)


async def cancellation_mid_run(h: Harness) -> None:
    h.stall["extract"] = 30
    bundle_id = await h.bundle(case_c_files(*PRELOADED))
    run_id, task = await h.start(bundle_id)
    await h.wait_for_stage(bundle_id, run_id, "extract")
    task.cancel()
    await asyncio.wait({task}, timeout=10)
    h.writes.append(("task_cancelled", task.cancelled()))


async def a_reaped_run_cannot_finish(h: Harness) -> None:
    gate = asyncio.Event()
    h.stall["extract"] = gate
    bundle_id = await h.bundle(case_c_files(*PRELOADED))
    run_id, task = await h.start(bundle_id)
    await h.wait_for_stage(bundle_id, run_id, "extract")
    stale = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
    firestore._IN_MEMORY_RUNS[f"{bundle_id}:{run_id}"]["updated_at"] = stale
    reaped = await orchestrator.reap_stale(bundle_id)
    h.writes.append(("reaped", reaped))
    gate.set()
    await asyncio.wait({task}, timeout=10)


@dataclass(frozen=True)
class Scenario:
    name: str
    steps: Callable[[Harness], Awaitable[None]]


SCENARIOS = [
    Scenario("case C iteration 1", case_c_iteration_1),
    Scenario("case C iterations 1 and 2", case_c_iteration_2),
    Scenario("net/gross weight mismatch", weight_mismatch),
    Scenario("HS mismatch invoice vs packing list", hs_mismatch_invoice_vs_packing_list),
    Scenario("MTC declares a different HS", mtc_declares_a_different_hs),
    Scenario("coffee described with the pipe code", coffee_described_with_the_pipe_code),
    Scenario("duplicate documents", duplicate_documents),
    Scenario("an UNKNOWN document", an_unknown_document),
    Scenario("low-confidence field", a_low_confidence_field),
    Scenario("a stage raises (ground), unexpected error", a_stage_raises_an_unexpected_error),
    Scenario("a stage raises (ground), domain error", a_stage_raises_a_domain_error),
    Scenario("deadline expiry", the_deadline_expires),
    Scenario("cancellation mid-run", cancellation_mid_run),
    Scenario("reaped run (fencing)", a_reaped_run_cannot_finish),
]


async def collect(scenario: Scenario, engine: str) -> dict[str, Any]:
    """Run ``scenario`` under ``engine`` against fresh stores and return the normalised record of everything observable."""
    with pytest.MonkeyPatch.context() as mp:
        reset_state()
        mp.setattr(settings, "pipeline_engine", engine)
        async with api_client() as client:
            harness = Harness(client, mp)
            await scenario.steps(harness)
            await asyncio.sleep(0.05)
            return await harness.snapshot()


async def compare(scenario: Scenario) -> tuple[str | None, dict[str, Any], dict[str, Any]]:
    native = await collect(scenario, "native")
    adk = await collect(scenario, "adk")
    return first_difference(native, adk), native, adk
