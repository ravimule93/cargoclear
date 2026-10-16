"""The Android client's copies of the API shapes and of the correction address tables (android/core/model) must equal the backend's.

Same job as test_corrections_contract.py does for the web client, for the same reason: the backend is the authority and nothing generates
the Kotlin, so this test is what keeps them together. It reads the Kotlin source, not a build, so it needs no Android toolchain.

Two things are checked:
  * the correction field tables (HEADER_FIELDS, LINE_FIELDS, ROW_LISTS, WEIGHT_FIELDS) are the same lists as in domain/corrections.py;
  * every Kotlin DTO of a backend response names exactly the fields of its Pydantic model (the wire names: `@SerialName`, else the property).

The Kotlin tests decode the payloads recorded from the demo backend (android/fixtures) strictly, which checks the same thing from the other
side: a field the backend really sends that the DTOs lack fails there.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import re
import types
import typing
from pathlib import Path

import pytest

from app.domain import corrections as c
from app.domain import schemas
from app.services import audit, preprocess, signing
from app.api.v1 import bundles as bundles_routes
from app.api.v1 import prefill as prefill_routes
from tests.support import scans
from tests.unit.test_deskew import GOLDEN_DESKEW_5, GOLDEN_ROTATED_270_DESKEW_4

ANDROID_DIR = Path(__file__).resolve().parents[3] / "android"
MODEL_DIR = ANDROID_DIR / "core" / "model" / "src" / "main" / "kotlin" / "com" / "cargoclear" / "japac" / "core" / "model"
MODEL_TESTS = ANDROID_DIR / "core" / "model" / "src" / "test" / "kotlin" / "com" / "cargoclear" / "japac" / "core" / "model"


def source(name: str) -> str:
    return (MODEL_DIR / name).read_text(encoding="utf-8")


def without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


# ---------------------------------------------------------------------------
# correction field tables
# ---------------------------------------------------------------------------


def kotlin_list(text: str, name: str) -> list[str]:
    match = re.search(rf"val {name}: (?:List|Set)<String> = (?:list|set)Of\((.*?)\n\)", without_comments(text), re.DOTALL)
    assert match, f"{name} not found in android/core/model/.../Corrections.kt"
    return re.findall(r'"([a-z_]+)"', match.group(1))


def test_the_correction_tables_are_the_same_in_kotlin_and_python() -> None:
    kt = source("Corrections.kt")
    assert kotlin_list(kt, "HEADER_FIELDS") == list(c.HEADER_FIELDS)
    assert kotlin_list(kt, "LINE_FIELDS") == list(c.LINE_FIELDS)
    assert kotlin_list(kt, "ROW_LISTS") == list(c.ROW_LISTS)


def test_the_fields_the_app_gives_a_unit_box_are_the_ones_the_backend_treats_as_weights() -> None:
    backend = {f for f, kind in {**c.HEADER_FIELDS, **c.LINE_FIELDS}.items() if kind == "weight"}
    assert set(kotlin_list(source("Corrections.kt"), "WEIGHT_FIELDS")) == backend


# ---------------------------------------------------------------------------
# DTO field names
# ---------------------------------------------------------------------------


def constructor_parameters(text: str, class_name: str) -> list[str]:
    """Wire names of the primary constructor of `data class <class_name>(...)`: `@SerialName("x") val y` is "x", a bare `val y` is "y"."""
    code = without_comments(text)
    start = code.index(f"data class {class_name}(") + len(f"data class {class_name}(")
    depth, end = 1, start
    while depth:
        char = code[end]
        depth += (char == "(") - (char == ")")
        end += 1
    parameters, current, nesting = [], "", 0
    for char in code[start : end - 1]:
        if char in "(<[":
            nesting += 1
        elif char in ")>]":
            nesting -= 1
        if char == "," and nesting == 0:
            parameters.append(current)
            current = ""
        else:
            current += char
    parameters.append(current)

    names = []
    for parameter in (p.strip() for p in parameters if p.strip()):
        serial = re.search(r'@SerialName\("([^"]+)"\)', parameter)
        plain = re.search(r"\bval\s+(\w+)", parameter)
        assert plain, f"cannot read parameter {parameter!r} of {class_name}"
        names.append(serial.group(1) if serial else plain.group(1))
    return names


PAIRS = [
    ("Assessment.kt", "BBox", schemas.BBox),
    ("Assessment.kt", "CheckResult", schemas.CheckResult),
    ("Assessment.kt", "GroundingFinding", schemas.GroundingFinding),
    ("Assessment.kt", "MissingEvidence", schemas.MissingEvidence),
    ("Assessment.kt", "ReasoningDelta", schemas.ReasoningDelta),
    ("Assessment.kt", "ConfidenceResult", schemas.ConfidenceResult),
    ("Assessment.kt", "DutyLine", schemas.DutyLine),
    ("Assessment.kt", "ValuationEstimate", schemas.ValuationEstimate),
    ("Assessment.kt", "AppliedCorrection", schemas.AppliedCorrection),
    ("Assessment.kt", "AssessmentIteration", schemas.AssessmentIteration),
    ("Bundle.kt", "DocumentRecord", schemas.DocumentResponse),
    ("Bundle.kt", "DocumentDeleted", schemas.DocumentDeletedResponse),
    ("Bundle.kt", "Bundle", schemas.BundleResponse),
    ("Bundle.kt", "CreateBundleRequest", schemas.CreateBundleRequest),
    ("Stream.kt", "RunResponse", schemas.RunResponse),
    ("BBoxMapping.kt", "TransformMetadataResponse", schemas.TransformMetadataResponse),
    ("Corrections.kt", "CorrectionRequest", schemas.CorrectionRequest),
    ("Corrections.kt", "RevertCorrectionRequest", schemas.RevertCorrectionRequest),
    ("Corrections.kt", "CorrectionRecord", schemas.CorrectionRecord),
    ("Corrections.kt", "CorrectionsResponse", schemas.CorrectionsResponse),
]


@pytest.mark.parametrize(("file", "kotlin_class", "model"), PAIRS, ids=[p[1] for p in PAIRS])
def test_a_kotlin_dto_names_the_fields_its_backend_model_has(file: str, kotlin_class: str, model: type) -> None:
    kotlin = set(constructor_parameters(source(file), kotlin_class))
    backend = set(model.model_fields)
    assert kotlin == backend, f"{kotlin_class}: only in Kotlin {sorted(kotlin - backend)}, only in the backend {sorted(backend - kotlin)}"


def test_the_audit_dtos_name_what_the_audit_routes_send() -> None:
    """The audit routes return plain dicts, so there is no model to compare with: ask the code that builds them."""
    event = audit._build_event("bnd-1", 1, "BUNDLE_CREATED", "user", {}, "GENESIS", 1)
    assert set(constructor_parameters(source("Audit.kt"), "AuditEvent")) == set(event)

    check = signing.SignatureCheck(1, 1, "h", None, "kms", "k", "a", True).as_dict()
    assert set(constructor_parameters(source("Audit.kt"), "SignatureCheck")) == set(check)

    summary = asyncio.run(signing.summarize([], "bnd-1"))
    assert set(constructor_parameters(source("Audit.kt"), "AuditSignature")) == set(summary)

    returned = re.search(r"return \{(.*?)\n    \}", inspect.getsource(bundles_routes.get_audit), re.DOTALL).group(1)
    assert set(constructor_parameters(source("Audit.kt"), "AuditResponse")) == set(re.findall(r'"(\w+)":', returned))


def test_the_signature_statuses_are_the_ones_the_backend_can_say() -> None:
    code = re.sub(r'""".*?"""', "", inspect.getsource(signing.summarize), flags=re.DOTALL)
    backend = set(re.findall(r'"([A-Z_]{4,})"', code))
    kotlin = set(re.findall(r'\("([A-Z_]+)"\)', re.search(r"enum class SignatureStatus.*?;", source("Audit.kt"), re.DOTALL).group(0)))
    assert kotlin == backend, f"only in Kotlin {sorted(kotlin - backend)}, only in the backend {sorted(backend - kotlin)}"


def test_the_correction_kinds_are_the_ones_the_backend_records() -> None:
    backend = set(typing.get_args(schemas.CorrectionRecord.model_fields["kind"].annotation))
    block = re.search(r"enum class CorrectionKind \{(.*?)\}", without_comments(source("Corrections.kt")), re.DOTALL).group(1)
    assert set(re.findall(r'@SerialName\("([a-z]+)"\)', block)) == backend


def test_the_editor_stops_at_the_limits_the_backend_enforces() -> None:
    kt = source("Corrections.kt")

    def limit(model: type, field: str) -> int:
        return next(m.max_length for m in model.model_fields[field].metadata if hasattr(m, "max_length"))

    assert int(re.search(r"const val MAX_VALUE = (\d+)", kt).group(1)) == limit(schemas.CorrectionRequest, "value") == limit(schemas.CorrectionRequest, "reason")
    assert int(re.search(r"const val MAX_UNIT = (\d+)", kt).group(1)) == limit(schemas.CorrectionRequest, "unit")


def test_the_prefill_file_is_named_as_the_backend_names_its_download() -> None:
    pack = types.SimpleNamespace(bundle_id="bnd-1", assessment=types.SimpleNamespace(iteration=2))
    template = re.search(r'"(cargoclear-prefill-[^"]+)"', source("Prefill.kt")).group(1)
    for extension in ("json", "pdf"):
        kotlin = template.replace("$bundleId", "bnd-1").replace("$iteration", "2").replace("${format.extension}", extension)
        assert kotlin == prefill_routes._filename(pack, extension)


def test_the_meta_dto_names_what_the_meta_route_sends() -> None:
    kotlin = set(constructor_parameters(source("Meta.kt"), "Meta"))
    assert kotlin == {"app_mode", "data_source_policy", "pipeline_engine"}


def test_the_error_envelope_dto_names_what_the_error_handlers_send() -> None:
    kotlin = set(constructor_parameters(source("ErrorEnvelope.kt"), "ErrorEnvelope"))
    assert kotlin == {"code", "message", "detail", "request_id"}


def test_the_parser_reads_a_parameter_list_with_nested_generics_and_defaults() -> None:
    text = 'data class X(@SerialName("a_b") val aB: Map<String, List<Int>>? = null, val c: List<String> = emptyList(), /* note, with a comma */ val d: Int)'
    assert constructor_parameters(text, "X") == ["a_b", "c", "d"]


def test_a_drifted_table_is_detected() -> None:
    kt = source("Corrections.kt").replace('    "consignee",\n', "", 1)
    assert kotlin_list(kt, "HEADER_FIELDS") != list(c.HEADER_FIELDS)


def test_a_drifted_dto_is_detected() -> None:
    kt = source("Assessment.kt").replace('@SerialName("check_id")', '@SerialName("check_ident")', 1)
    assert set(constructor_parameters(kt, "CheckResult")) != set(schemas.CheckResult.model_fields)


# ---------------------------------------------------------------------------
# page geometry: the viewer's mapping of a box back onto the original page
# ---------------------------------------------------------------------------


def test_the_kotlin_transform_metadata_names_every_key_the_preprocessing_records() -> None:
    """transform_meta is a list of untyped dicts, so the schema cannot say what is in it: ask the real preprocessing."""
    result = asyncio.run(preprocess.run({"raw_bytes": scans.pdf(scans.make_page()), "document_id": "doc-1"}))
    emitted = set(result["transform_meta"][0])
    known = set(constructor_parameters(source("BBoxMapping.kt"), "TransformMetadata"))
    assert emitted <= known, f"keys the backend records that the app's TransformMetadata does not name: {sorted(emitted - known)}"


def kotlin_numbers(text: str, name: str) -> list[float]:
    """The numbers of `val <name> = listOf(listOf(..), ..)` in a Kotlin test file, row by row."""
    match = re.search(rf"val {name} = listOf\((.*?)\n    \)", without_comments(text), re.DOTALL)
    assert match, f"{name} not found in the Kotlin tests"
    return [float(n) for n in re.findall(r"-?\d+\.\d+", match.group(1))]


def flatten(matrix: list[list[float]]) -> list[float]:
    return [float(v) for row in matrix for v in row]


def test_the_kotlin_tests_are_held_to_the_same_matrices_as_the_backend_and_the_web() -> None:
    kt = (MODEL_TESTS / "LogicTest.kt").read_text(encoding="utf-8")
    assert kotlin_numbers(kt, "goldenDeskew5") == pytest.approx(flatten(GOLDEN_DESKEW_5), abs=1e-9)
    assert kotlin_numbers(kt, "goldenRotated270Deskew4") == pytest.approx(flatten(GOLDEN_ROTATED_270_DESKEW_4), abs=1e-9)


VIEWER_FIXTURES = sorted((ANDROID_DIR / "fixtures" / "viewer").glob("*.json"))


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


@pytest.mark.parametrize("path", VIEWER_FIXTURES, ids=[p.stem for p in VIEWER_FIXTURES])
def test_the_recorded_alignment_cases_still_carry_their_marker_onto_the_page(path: Path) -> None:
    """The cases the Android viewer is tested on (android/tools/make_alignment_fixtures.py): the backend's own affine, applied to the
    marker the model would cite, must land on the marker as a renderer shows the page."""
    record = json.loads(path.read_text(encoding="utf-8"))
    [meta] = record["transform_metadata"]["transform_meta"]
    cited, actual = record["processed_marker"], record["original_marker"]
    corners = [preprocess.apply_affine(meta["processed_to_source_affine"], x, y) for x, y in
               ((cited["xmin"], cited["ymin"]), (cited["xmax"], cited["ymin"]), (cited["xmin"], cited["ymax"]), (cited["xmax"], cited["ymax"]))]
    clamp = lambda v: min(1000.0, max(0.0, v))  # noqa: E731
    mapped = (clamp(min(x for x, _ in corners)), clamp(min(y for _, y in corners)), clamp(max(x for x, _ in corners)), clamp(max(y for _, y in corners)))
    assert iou(mapped, (actual["xmin"], actual["ymin"], actual["xmax"], actual["ymax"])) >= 0.85


def test_there_are_alignment_cases_for_rotation_tilt_both_and_a_rotated_pdf() -> None:
    assert {p.stem for p in VIEWER_FIXTURES} >= {"clean", "skew5", "skew-8", "sideways90-skew4", "sideways270-skew4", "sideways180", "pdf-rotate90"}



# ---------------------------------------------------------------------------
# what the Android app does and does not do: the claims of docs/CLAIMS.md C-60 and C-65 rest on these
# ---------------------------------------------------------------------------

MAIN_SOURCES = [p for pattern in ("app/src/main/**/*.kt", "core/*/src/main/**/*.kt") for p in sorted(ANDROID_DIR.glob(pattern))]
VERDICTS = ("COMPLIANT_FOR_SUBMISSION", "MISSING_EVIDENCE", "MATERIAL_CONTRADICTION", "SPECIALIST_REVIEW_REQUIRED")


def test_there_is_android_source_to_check() -> None:
    assert len(MAIN_SOURCES) > 50


def test_no_android_code_builds_a_verdict() -> None:
    """C-60: a status reaches the screen only as the service sent it. The four verdict names are written out once (the enum that reads the wire
    value) and named elsewhere only to be shown or compared: the status pill, the announcements, the notification, the pre-fill caveat."""
    shown_or_compared = {"Assessment.kt", "AssessmentTab.kt", "StatusPill.kt", "RunNotifier.kt", "Prefill.kt"}
    literal = re.compile(r'"(' + "|".join(VERDICTS) + r')"')
    named = re.compile(r"\bStatus\.(" + "|".join(VERDICTS) + r")\b")
    offenders = []
    for path in MAIN_SOURCES:
        code = without_comments(path.read_text(encoding="utf-8"))
        if literal.search(code) and path.name != "Assessment.kt":
            offenders.append(f"{path.relative_to(ANDROID_DIR)} writes a verdict as a string")
        if named.search(code) and path.name not in shown_or_compared:
            offenders.append(f"{path.relative_to(ANDROID_DIR)} names a verdict outside the files that show or compare one")
        # nothing assigns or copies a status other than from what was decoded
        if re.search(r"\bstatus\s*=\s*(Status\.|\")", code) and path.name != "Assessment.kt":
            offenders.append(f"{path.relative_to(ANDROID_DIR)} assigns a status")
    assert not offenders, "\n".join(offenders)


def test_no_android_code_writes_a_log() -> None:
    """Part of C-65 and of the About screen's sentence: bundle ids are the only access control the backend has, and the app's own code writes no logs (a library may log its own work)."""
    pattern = re.compile(r"\bLog\.[a-z]\(|\bprintln\(|\bTimber\.|printStackTrace\(|\bLogger\b|\bandroid\.util\.Log\b")
    offenders = [str(p.relative_to(ANDROID_DIR)) for p in MAIN_SOURCES if pattern.search(without_comments(p.read_text(encoding="utf-8")))]
    assert not offenders, f"logging in: {offenders}"


def manifest() -> str:
    return (ANDROID_DIR / "app" / "src" / "main" / "AndroidManifest.xml").read_text(encoding="utf-8")


APP_PERMISSIONS = {
    "android.permission.INTERNET",
    "android.permission.ACCESS_NETWORK_STATE",
    "android.permission.POST_NOTIFICATIONS",
    "android.permission.FOREGROUND_SERVICE",
    "android.permission.FOREGROUND_SERVICE_DATA_SYNC",
}

# what the libraries merge into the built app's manifest (WorkManager, and the profile installer that Compose brings)
LIBRARY_PERMISSIONS = {
    "android.permission.RECEIVE_BOOT_COMPLETED",
    "android.permission.WAKE_LOCK",
    "com.cargoclear.japac.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION",
}
APP_DOOR = ("activity", "com.cargoclear.japac.MainActivity", None)
LIBRARY_EXPORTED = {
    ("service", "androidx.work.impl.background.systemjob.SystemJobService", "android.permission.BIND_JOB_SERVICE"),
    ("receiver", "androidx.work.impl.diagnostics.DiagnosticsReceiver", "android.permission.DUMP"),
    ("receiver", "androidx.profileinstaller.ProfileInstallReceiver", "android.permission.DUMP"),
}


def test_the_apps_own_manifest_asks_only_for_what_the_app_uses_and_exports_only_its_door() -> None:
    """C-65: a new permission or a new exported component must be a conscious change to this list. This is the app's OWN manifest; the built app's
    is checked below."""
    text = re.sub(r"<!--.*?-->", "", manifest(), flags=re.DOTALL)
    permissions = set(re.findall(r'<uses-permission android:name="([^"]+)"', text))
    assert permissions == APP_PERMISSIONS
    exported = re.findall(r'<(activity|service|receiver|provider)\b[^>]*?android:name="([^"]+)"[^>]*?android:exported="true"', text, flags=re.DOTALL)
    assert exported == [("activity", ".MainActivity")]
    assert 'android:allowBackup="false"' in text
    assert "android:debuggable" not in text and "usesCleartextTraffic" not in text


BUILT_RECORD = ANDROID_DIR / "fixtures" / "hosted_release_manifest.json"
BUILT_MERGED = ANDROID_DIR / "app" / "build" / "intermediates" / "merged_manifests" / "hostedRelease" / "processHostedReleaseManifest" / "AndroidManifest.xml"


def manifest_summary_tool():
    spec = importlib.util.spec_from_file_location("manifest_summary", ANDROID_DIR / "tools" / "manifest_summary.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_built_app_asks_for_and_exports_only_what_is_known() -> None:
    """C-65: the manifest that ships is the app's own plus what the libraries merge in (eight permissions, four exported components, not five and
    one). The record is android/fixtures/hosted_release_manifest.json (android/tools/manifest_summary.py --write); a new entry can only come in by
    updating it and the lists above."""
    recorded = json.loads(BUILT_RECORD.read_text(encoding="utf-8"))
    assert set(recorded["permissions"]) == APP_PERMISSIONS | LIBRARY_PERMISSIONS
    assert len(recorded["permissions"]) == len(set(recorded["permissions"]))
    exported = {(c["kind"], c["name"], c["permission"]) for c in recorded["exported"]}
    assert exported == {APP_DOOR} | LIBRARY_EXPORTED
    # the app's door is the only one anybody can knock on: the others are open only to a caller that holds a permission the system keeps for itself
    assert [c["name"] for c in recorded["exported"] if not c["permission"]] == ["com.cargoclear.japac.MainActivity"]


def test_the_record_of_the_built_manifest_is_what_the_build_produces() -> None:
    """Runs where an Android build has been made (./gradlew :app:processHostedReleaseManifest); without one there is nothing to compare."""
    if not BUILT_MERGED.exists():
        pytest.skip("no merged manifest here: run ./gradlew :app:processHostedReleaseManifest in android/ first")
    built = manifest_summary_tool().summarise(BUILT_MERGED.read_text(encoding="utf-8"))
    assert built == json.loads(BUILT_RECORD.read_text(encoding="utf-8")), "run android/tools/manifest_summary.py --write and update the lists in this test"


def test_the_hosted_build_trusts_only_https_and_the_system_certificate_authorities() -> None:
    """C-65: no cleartext, no user-installed certificate authority, no pinning (Cloud Run certificates rotate)."""
    config = (ANDROID_DIR / "app" / "src" / "hosted" / "res" / "xml" / "network_security_config.xml").read_text(encoding="utf-8")
    config = re.sub(r"<!--.*?-->", "", config, flags=re.DOTALL)
    assert re.search(r'<base-config cleartextTrafficPermitted="false"', config)
    assert "domain-config" not in config
    assert 'src="user"' not in config and "pin-set" not in config
    assert re.findall(r'<certificates src="(\w+)"', config) == ["system"]


def test_cleartext_is_for_the_developers_own_machine_only_and_never_ships() -> None:
    local = re.sub(r"<!--.*?-->", "", (ANDROID_DIR / "app" / "src" / "local" / "res" / "xml" / "network_security_config.xml").read_text(encoding="utf-8"), flags=re.DOTALL)
    assert re.findall(r"<domain includeSubdomains=\"false\">([^<]+)</domain>", local) == ["10.0.2.2", "localhost", "127.0.0.1"]
    gradle = (ANDROID_DIR / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert 'variant.buildType == "release" && local) variant.enable = false' in gradle, "the release variant of the cleartext flavor must stay disabled"
    assert 'variant.buildType == "r8check" && !local) variant.enable = false' in gradle, "the debug-signed minified build must exist only for the cleartext flavor"
    assert "must live outside the repository" in gradle, "a release keystore inside the repository must be refused"


def test_nothing_of_the_app_goes_into_a_cloud_backup_or_a_device_transfer() -> None:
    rules = (ANDROID_DIR / "app" / "src" / "main" / "res" / "xml" / "data_extraction_rules.xml").read_text(encoding="utf-8")
    for section in ("cloud-backup", "device-transfer"):
        body = re.search(rf"<{section}>(.*?)</{section}>", rules, re.DOTALL).group(1)
        assert set(re.findall(r'<exclude domain="(\w+)"', body)) == {"root", "file", "database", "sharedpref", "external"}


def test_the_about_screen_says_what_the_register_says_about_the_rule_tables() -> None:
    """C-04 is to be said every time a rate, limit or duty figure is shown; the About screen quotes it, so it is checked against the register."""
    register = (ANDROID_DIR.parent / "docs" / "CLAIMS.md").read_text(encoding="utf-8")
    phrase = "demo-curated, unverified, and partly placeholders"
    assert phrase in register
    assert phrase in (ANDROID_DIR / "app" / "src" / "main" / "res" / "values" / "strings.xml").read_text(encoding="utf-8")


def test_the_titles_of_the_checks_that_end_in_a_document_id_are_the_web_apps() -> None:
    """P-001, P-002, T-001 and L-001 have one check per document, so their titles are matched by prefix, in CheckList.tsx and CheckTitles.kt."""
    web = (ANDROID_DIR.parent / "frontend" / "components" / "assess" / "CheckList.tsx").read_text(encoding="utf-8")
    kotlin = source("CheckTitles.kt")
    for prefix, title in (
        ("P-001-", "Pages Not Read"),
        ("P-002-", "Pages Skipped (Terms and Conditions)"),
        ("T-001-", "Document Type Differs From the Upload"),
        ("L-001-", "Values Not in Latin Script"),
    ):
        assert f'startsWith("{prefix}")' in web and f'"{title}"' in web, (prefix, "web")
        assert f'startsWith("{prefix}") -> "{title}"' in kotlin, (prefix, "kotlin")
