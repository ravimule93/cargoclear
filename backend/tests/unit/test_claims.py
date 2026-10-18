"""docs/CLAIMS.md and the outward-facing files, held to the claim-audit rules.

* every claim in the register has one label, evidence that exists, and the counts in its header match the table;
* a label cannot move without its evidence: a row that says PROVEN for the live stack needs a live measurement, and a live
  measurement that passed forces the row off STUBBED;
* the outward-facing files (README, Product.md, the FAQ, the runbooks, the UI copy) carry none of the phrases that usually hide an
  invented number or an unearned superlative;
* the claims that were deleted, and the statements that went stale, do not come back;
* the two boundary claims that can be checked mechanically are: the backend has no outbound HTTP client and no route that
  files, submits or pays.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT

REGISTER = REPO_ROOT / "docs" / "CLAIMS.md"
LABELS = ("PROVEN", "STUBBED", "ASSUMED", "DELETED")
ROW = re.compile(r"^\| (C-\d+) \| (.+?) \| (PROVEN|STUBBED|ASSUMED|DELETED) \| (.+?) \| (.+?) \|\s*$")

OUTWARD = [
    "README.md", "Product.md", "context.md",
    "docs/FAQ_ONBOARDING.md", "docs/HOW_TO_RUN_AND_DEMO.md", "docs/PREFILL_PACK.md", "docs/SCALING_AND_INTEGRITY.md",
    "docs/GCP_VERIFICATION.md", "backend/app/main.py", "backend/app/reference/README.md",
]
HISTORICAL = ["docs/mvp_draft2_Product & Technical Specification.md", "docs/mvp_draft_2_Technical implementation plan.md"]


def outward_files() -> list[Path]:
    files = [REPO_ROOT / name for name in OUTWARD]
    for pattern in ("frontend/app/**/*.tsx", "frontend/components/**/*.tsx"):
        files += sorted(REPO_ROOT.glob(pattern))
    return files


def register_rows() -> list[dict[str, str]]:
    rows = []
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        if line.startswith("| C-"):
            match = ROW.match(line)
            assert match, f"malformed register row: {line[:120]}"
            rows.append(dict(zip(("id", "claim", "label", "evidence", "say"), match.groups())))
    return rows


def live_measurements() -> list[dict]:
    found = []
    for path in sorted((REPO_ROOT / "docs" / "measurements").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["kind"] == "e2e" and data["stack"].get("app_mode") == "live":
            found.append(data)
    return found


# --- the register ----------------------------------------------------------------------------------------------------------


def test_the_register_is_well_formed_and_its_counts_are_true() -> None:
    rows = register_rows()
    ids = [r["id"] for r in rows]
    assert ids == [f"C-{n:02d}" for n in range(1, len(ids) + 1)], "ids are unique and consecutive"
    header = re.search(r"PROVEN: (\d+) \| STUBBED: (\d+) \| ASSUMED: (\d+) \| DELETED: (\d+)", REGISTER.read_text(encoding="utf-8"))
    assert header, "the verdict block has no counts"
    stated = tuple(int(n) for n in header.groups())
    actual = tuple(sum(r["label"] == label for r in rows) for label in LABELS)
    assert stated == actual, f"the header says {stated}, the table has {actual} (PROVEN, STUBBED, ASSUMED, DELETED)"


def _evidence_paths(cell: str) -> list[str]:
    """The repo paths named in a backticked span of an evidence cell (commands and bare words are not paths)."""
    paths = []
    for token in re.findall(r"`([^`]+)`", cell):
        if " " in token or token.startswith("cd "):
            continue
        if "/" in token or re.search(r"\.(py|ts|tsx|json|md|sh|yaml)(::|$)", token):
            paths.append(token)
    return paths


def test_every_piece_of_evidence_exists() -> None:
    for row in register_rows():
        paths = _evidence_paths(row["evidence"])
        links = re.findall(r"\]\((https?://[^)]+)\)", row["evidence"])
        if row["label"] == "PROVEN":
            assert paths or links or "run on 20" in row["evidence"], f"{row['id']}: PROVEN with no evidence a reader can open"
        for token in paths:
            file_part, _, test_name = token.partition("::")
            target = REPO_ROOT / file_part
            assert target.exists(), f"{row['id']}: evidence {file_part} does not exist"
            if test_name:
                assert re.search(rf"def {re.escape(test_name)}\b", target.read_text(encoding="utf-8")), (
                    f"{row['id']}: {file_part} has no test named {test_name}"
                )


def test_a_claim_that_is_not_proven_says_what_to_say_instead() -> None:
    for row in register_rows():
        assert len(row["say"].strip()) > 6, f"{row['id']}: no wording for what may be said"
        if row["label"] == "STUBBED":
            assert row["evidence"].strip(), f"{row['id']}: STUBBED with nothing named as built"


def test_a_label_cannot_move_without_its_evidence() -> None:
    """C-08 (live journeys reach the expected statuses) and C-09 (live extraction accuracy) are STUBBED until a live measurement
    exists, and cannot stay STUBBED once one has passed: the register follows the data, in both directions."""
    rows = {r["id"]: r for r in register_rows()}
    live = live_measurements()

    def passed(case: str) -> bool:
        runs = [m for m in live if m.get("case") == case and not (m.get("options") or {}).get("corrections")]
        return any(len(m["runs"]) >= 5 and all(r["ok"] for r in m["runs"]) for m in runs)

    both = passed("c") and passed("d")
    if rows["C-08"]["label"] == "PROVEN":
        assert both, "C-08 is PROVEN but docs/measurements/ has no passing live run (>= 5 runs) of both Case C and Case D"
    if both:
        assert rows["C-08"]["label"] == "PROVEN", "a passing live run of Case C and D is recorded: move C-08 to PROVEN and name the files"
        assert "docs/measurements/" in rows["C-08"]["evidence"]

    extraction = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted((REPO_ROOT / "docs" / "measurements").glob("*.json"))
    ]
    has_extraction = any(m["kind"] == "extraction" and m["environment"].get("model") for m in extraction)
    if rows["C-09"]["label"] == "PROVEN":
        assert has_extraction, "C-09 is PROVEN but no extraction report from the real model is in docs/measurements/"
    if has_extraction:
        assert rows["C-09"]["label"] == "PROVEN" or "docs/measurements/" in rows["C-09"]["evidence"], (
            "an extraction report is recorded: update C-09 (PROVEN, or STUBBED naming the failures) and name the file"
        )


def test_historical_documents_point_at_the_register() -> None:
    for name in HISTORICAL:
        head = "\n".join((REPO_ROOT / name).read_text(encoding="utf-8").splitlines()[:14])
        assert "docs/CLAIMS.md" in head or "CLAIMS.md" in head, f"{name} makes claims and does not say where they are audited"


# --- the outward-facing files ----------------------------------------------------------------------------------------------

RISKY = [
    (r"\$\s?\d", "a currency amount"),
    (r"\b\d[\d,.]*\s?(billion|million|trillion|bn)\b", "a market size"),
    (r"\b\d+(\.\d+)?\s?(x|×)\s+(faster|cheaper|more|less)", "a multiple"),
    (r"\b\d+(\.\d+)?\s?(%|percent)\s+(faster|more accurate|fewer|less|reduction|savings|improvement|lower|higher|cheaper)", "a percentage gain"),
    (r"\b(reduc|cut|sav|improv)\w*\s+[^.\n]{0,30}\b\d+(\.\d+)?\s?(%|percent)", "a percentage gain"),
    (r"hours? to minutes?|minutes? to seconds?", "a before/after time claim"),
    (r"world'?s first|first[- ]ever|industry[- ]leading|state[- ]of[- ]the[- ]art|best[- ]in[- ]class|\bonly (tool|platform|product|solution)\b"
     r"|game[- ]chang|unprecedented|zero[- ]hallucination|never (wrong|hallucinat)|100 ?% (accura|correct)|\bguarantee[sd]?\b", "a superlative"),
    (r"\b(accuracy|accurate|precision|recall|F1)\b[^\n]{0,60}\d+(\.\d+)?\s?(%|percent)", "an accuracy figure"),
    (r"\d+(\.\d+)?\s?(%|percent)[^\n]{0,40}\b(accuracy|accurate|precision|recall)\b", "an accuracy figure"),
    (r"\b(takes|taking|in (under|less than|about|around)|under|within|latency of|latency|p50|p95|median)\s+(about\s+|around\s+|~)?(a\s+)?"
     r"(\d+(\.\d+)?|second|minute)\s?(s\b|sec|seconds?|ms\b|minutes?|mins?)", "a latency"),
    (r"takes about a (second|minute)", "a latency"),
    (r"real[- ]time|\binstant(ly)?\b|\beffortless|\bcutting[- ]edge\b|\bAI[- ]powered\b|\bproduction[- ]ready\b|\benterprise[- ]grade\b",
     "an unmeasured adjective"),
]


BAD_SENTENCES = [
    "CargoClear cuts audit time by 80 %.", "Saves $4,000 per shipment.", "A $42B market.", "Analysis takes 31 seconds.",
    "The world's first customs assistant.", "100% accurate on every bundle.", "Extraction accuracy of 97.5 %.",
    "From hours to minutes.", "Real-time analysis.", "An AI-powered workbench.", "Results in under 45 s.", "median 12 s",
    "10x faster than manual review.", "Zero hallucination.", "Reduces errors by 40 percent.",
]
GOOD_SENTENCES = [
    "Heat TH-77121 reports 0.35 % chromium, above the 0.30 % threshold.", "A 300-second request timeout.", "The run deadline is 1,200 seconds.",
    "Chinese-origin seamless tubes.", "Cr 0.35%", "Weights are compared within the larger of 0.5 % and 5 kg.", "ASTM A106 allows 0.40 %.",
    "The skew is found to the nearest 0.1 degree.", "RATE_LIMIT_WRITES_PER_MINUTE=30",
]


@pytest.mark.parametrize("sentence", BAD_SENTENCES)
def test_the_guard_catches_the_phrases_it_exists_for(sentence: str) -> None:
    assert any(re.search(pattern, sentence, re.IGNORECASE) for pattern, _ in RISKY), sentence


@pytest.mark.parametrize("sentence", GOOD_SENTENCES)
def test_the_guard_leaves_domain_values_and_settings_alone(sentence: str) -> None:
    assert not any(re.search(pattern, sentence, re.IGNORECASE) for pattern, _ in RISKY), sentence


def test_outward_facing_files_carry_no_invented_statistic_or_superlative() -> None:
    compiled = [(re.compile(p, re.IGNORECASE), why) for p, why in RISKY]
    hits = []
    for path in outward_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern, why in compiled:
                found = pattern.search(line)
                if found:
                    hits.append(f"{path.relative_to(REPO_ROOT)}:{number}: {why}: {found.group(0)!r}")
    assert not hits, (
        "numbers and superlatives about the product belong in docs/MEASURED_RESULTS.md (generated) or docs/CLAIMS.md, not here:\n"
        + "\n".join(hits)
    )


DELETED = [
    (r"\$\s?42\s?B|42 ?billion", "the $42B market figure"),
    (r"80 ?% of (the )?paperwork", "the 80 % of paperwork figure"),
    (r"world'?s first", "'world's first'"),
    (r"files fraud", "'files fraud faithfully'"),
    (r"zero[- ]hallucination", "'zero hallucination'"),
    (r"adjudicator|adjudication workbench|adjudication alert", "'adjudicator' (the product is decision support)"),
    # statements that were true before Phase 3 and went stale; they contradict the code now
    (r"deskew_applied` remains false", "'deskew is not applied'"),
    (r"reversible deskew (transform|mapping) (has not yet been|is not yet) ", "'a reversible deskew does not exist'"),
    (r"is not horizontally safe", "'not horizontally safe' (it has an opt-in scale-out path now)"),
    (r"planned fix \(Firestore leases", "'leases are planned' (they are built)"),
]


def test_deleted_claims_do_not_come_back() -> None:
    hits = []
    for path in outward_files():
        text = path.read_text(encoding="utf-8")
        for pattern, why in DELETED:
            for found in re.finditer(pattern, text, re.IGNORECASE):
                hits.append(f"{path.relative_to(REPO_ROOT)}: {why}: {found.group(0)!r}")
    assert not hits, "\n".join(hits)


def test_non_repudiation_only_appears_to_be_denied() -> None:
    for path in outward_files():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"non-?repudiation", line, re.IGNORECASE):
                assert re.search(r"\b(not|never|no)\b", line, re.IGNORECASE), (
                    f"{path.relative_to(REPO_ROOT)}:{number}: non-repudiation may only be named to deny it: {line.strip()[:100]}"
                )


def test_the_readme_keeps_saying_nothing_was_verified_live_until_a_live_run_is_recorded() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    if not live_measurements():
        assert "Nothing in this repository has been verified against a real project" in readme, (
            "no live measurement is recorded, so the README may not stop saying that nothing was verified on Google Cloud"
        )


def test_the_documents_that_quote_numbers_point_at_the_page_that_owns_them() -> None:
    for name in ("README.md", "Product.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert "docs/CLAIMS.md" in text and "docs/MEASURED_RESULTS.md" in text, f"{name} must point at the claim register and the measurements"


# --- the boundary claims that a machine can check ----------------------------------------------------------------------------

FORBIDDEN_IMPORTS = {"httpx", "requests", "aiohttp", "urllib.request", "http.client", "smtplib", "ftplib", "socket", "telnetlib", "paramiko"}
# Two imports are not connections, and the test pins exactly what each is used for.
ALLOWED_USES = {
    ("backend/app/agents/extraction.py", "httpx"): {"TransportError"},   # classifying the SDK's exception, not making a request
    ("backend/app/repo/leases.py", "socket"): {"gethostname"},          # the instance's name for the lease owner field
}


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _attributes_used(path: Path, module: str) -> set[str]:
    return {
        node.attr
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == module
    }


def test_the_backend_has_no_outbound_http_client_and_no_route_files_or_pays() -> None:
    """C-01: CargoClear submits nothing and collects nothing. Application code opens no HTTP/mail/socket connection of its own
    (Google's client libraries are the only network users), and no route is named for filing, submitting or paying."""
    offenders = []
    for path in sorted((REPO_ROOT / "backend" / "app").rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        for name in sorted(_imports(path) & FORBIDDEN_IMPORTS):
            allowed = ALLOWED_USES.get((relative, name))
            if allowed is None:
                offenders.append(f"{relative}: imports {name}")
            elif not _attributes_used(path, name) <= allowed:
                offenders.append(f"{relative}: uses {name}.{sorted(_attributes_used(path, name) - allowed)}, allowed only {sorted(allowed)}")
    assert not offenders, "application code opens its own network connection:\n" + "\n".join(offenders)

    from app.main import app

    verbs = {"submit", "file", "lodge", "pay", "payment", "payments", "declare", "clear", "clearance", "send", "email"}
    for route in app.routes:
        path = getattr(route, "path", "")
        words = {part.lower() for part in re.split(r"[/_\-]", path) if part and not part.startswith("{")}
        assert not (words & verbs), f"route {path} suggests it files, submits or pays"


@pytest.mark.parametrize("name", HISTORICAL)
def test_the_historical_documents_exist(name: str) -> None:
    assert (REPO_ROOT / name).exists()
