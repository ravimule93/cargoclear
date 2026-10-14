"""Static guards for the checked-in Cloud Run deployment contract.

These tests deliberately inspect files only. They do not invoke Docker, gcloud,
Cloud Build, or a network service.
"""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def test_cloud_build_deploys_scripts_from_repository_root_with_runtime_identity() -> None:
    config = yaml.safe_load((ROOT / "cloudbuild.yaml").read_text(encoding="utf-8"))
    steps = {step["id"]: step for step in config["steps"]}

    for name, script in (("deploy-backend", "infra/deploy_api.sh"), ("deploy-frontend", "infra/deploy_ui.sh")):
        assert "dir" not in steps[name]
        assert f"bash ./{script}" in steps[name]["args"][-1]

    assert "RUNTIME_SERVICE_ACCOUNT=$_RUNTIME_SERVICE_ACCOUNT" in steps["deploy-backend"]["env"]
    assert "_RUNTIME_SERVICE_ACCOUNT" in config["substitutions"]
    assert "UI_SERVICE_ACCOUNT=$_UI_SERVICE_ACCOUNT" in steps["deploy-frontend"]["env"]
    assert "_UI_SERVICE_ACCOUNT" in config["substitutions"]


def test_api_deploy_is_single_instance_by_default_and_fails_closed_without_runtime_identity() -> None:
    script = (ROOT / "infra" / "deploy_api.sh").read_text(encoding="utf-8")

    assert 'RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:?' in script
    assert "--service-account \"${RUNTIME_SERVICE_ACCOUNT}\"" in script
    assert 'MIN_INSTANCES="${MIN_INSTANCES:-1}"' in script and 'MAX_INSTANCES="${MAX_INSTANCES:-1}"' in script
    assert '--max-instances "${MAX_INSTANCES}"' in script and '--min-instances "${MIN_INSTANCES}"' in script
    assert 'RUN_DISPATCH="${RUN_DISPATCH:-local}"' in script, "the default stays the always-on single instance"
    assert "--concurrency 80" in script
    assert '--timeout "${REQUEST_TIMEOUT}"' in script and "REQUEST_TIMEOUT=300" in script
    assert "--no-cpu-throttling" in script
    assert 'APP_MODE="live"' in script
    assert 'ENABLE_API_DOCS="false"' in script


def test_more_than_one_instance_needs_dispatched_runs_and_a_request_timeout_longer_than_a_run() -> None:
    script = (ROOT / "infra" / "deploy_api.sh").read_text(encoding="utf-8")
    local, cloudtasks = script.split("  local)\n", 1)[1].split("  cloudtasks)\n")

    assert 'if [ "${MAX_INSTANCES}" -gt 1 ]' in local and "exit 1" in local, "local dispatch refuses a scale-out"
    assert "REQUEST_TIMEOUT=300" in local
    assert 'TASKS_SERVICE_ACCOUNT="${TASKS_SERVICE_ACCOUNT:?' in cloudtasks
    assert "REQUEST_TIMEOUT=1500" in cloudtasks, "a worker request outlives RUN_TIMEOUT_SECONDS (1200)"
    assert 'RATE_LIMIT_BACKEND="${RATE_LIMIT_BACKEND:-firestore}"' in cloudtasks, "limits are shared once there are several instances"
    for name in ("RUN_DISPATCH", "RATE_LIMIT_BACKEND", "TASKS_QUEUE", "TASKS_LOCATION", "TASKS_SERVICE_ACCOUNT", "INTERNAL_CALLER_EMAIL"):
        assert f'{name}="${{' in script, name
    # the service URL is only known once it exists: set on a second revision, and the tasks identity may then invoke it
    assert '--update-env-vars "API_URL=${API_URL}"' in script
    assert 'add-iam-policy-binding cargoclear-api' in script and 'serviceAccount:${TASKS_SERVICE_ACCOUNT}' in script
    assert "allUsers" not in script.split("remove-iam-policy-binding")[0].split("add-iam-policy-binding")[-1], "never a public invoker"


def test_the_run_queue_has_a_service_wide_cap_a_takeover_friendly_retry_and_least_privilege_bindings() -> None:
    script = (ROOT / "infra" / "tasks" / "setup_queue.sh").read_text(encoding="utf-8")
    assert '--max-concurrent-dispatches "${MAX_CONCURRENT_RUNS}"' in script
    assert "--min-backoff 30s" in script, "longer than a moment: the dead executor's lease must have expired by the next delivery"
    assert "--max-attempts 5" in script
    assert 'RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:?' in script
    assert "tasks queues add-iam-policy-binding" in script and "roles/cloudtasks.enqueuer" in script, "enqueue on THIS queue only"
    assert "roles/iam.serviceAccountUser" in script
    assert "add-iam-policy-binding \"${TASKS_QUEUE}\"" in script
    code = [line for line in script.splitlines() if not line.lstrip().startswith("#")]
    assert not any("run.invoker" in line or "run services" in line for line in code), "the invoker binding on the API is made after it exists (deploy_api.sh)"

    ttl = (ROOT / "infra" / "firestore" / "setup_ttl.sh").read_text(encoding="utf-8")
    assert "--collection-group=ratelimits" in ttl and "expires_at" in ttl and "--enable-ttl" in ttl


def test_the_signing_key_is_an_ec_signing_key_in_the_data_residency_region_with_one_narrow_binding() -> None:
    script = (ROOT / "infra" / "kms" / "setup_signing_key.sh").read_text(encoding="utf-8")
    assert "--purpose asymmetric-signing" in script and "--default-algorithm ec-sign-p256-sha256" in script
    assert 'REGION="${REGION:-asia-south1}"' in script, "keys stay in the data-residency region"
    assert "kms keys add-iam-policy-binding" in script and "roles/cloudkms.signerVerifier" in script, "sign + read the public key of this key only"
    assert "projects add-iam-policy-binding" not in script
    api = (ROOT / "infra" / "deploy_api.sh").read_text(encoding="utf-8")
    assert 'SIGNING_KEY_VERSION="${SIGNING_KEY_VERSION}"' in api


def test_the_scaling_scripts_are_valid_shell() -> None:
    import subprocess

    for path in (
        "infra/deploy_api.sh", "infra/bootstrap.sh", "infra/tasks/setup_queue.sh", "infra/firestore/setup_ttl.sh",
        "infra/kms/setup_signing_key.sh",
    ):
        result = subprocess.run(["bash", "-n", str(ROOT / path)], capture_output=True, text=True)
        assert result.returncode == 0, f"{path}: {result.stderr}"


def test_the_iam_manifest_names_the_tasks_identity_and_what_it_may_do() -> None:
    import yaml

    roles = yaml.safe_load((ROOT / "infra" / "iam" / "roles.yaml").read_text(encoding="utf-8"))
    assert roles["tasks_roles"] == [], "the tasks identity has no project role"
    assert roles["tasks_resource_bindings"] == [{"resource": "cloud-run-service/cargoclear-api", "role": "roles/run.invoker"}]
    assert {(b["resource"], b["role"]) for b in roles["runtime_resource_bindings"]} == {
        ("cloud-tasks-queue/cargoclear-runs", "roles/cloudtasks.enqueuer"),
        ("service-account/cargoclear-tasks-sa", "roles/iam.serviceAccountUser"),
        ("kms-key/cargoclear/audit-head", "roles/cloudkms.signerVerifier"),
    }
    rules = (ROOT / "infra" / "firestore.rules").read_text(encoding="utf-8")
    assert "match /control/{controlId}" in rules and "match /ratelimits/{counterId}" in rules
    assert rules.count("allow read, write: if false;") == 2, "leases and counters are server-side only"


def test_ui_uses_a_runtime_server_only_api_url_for_proxy_and_sse() -> None:
    ui_script = (ROOT / "infra" / "deploy_ui.sh").read_text(encoding="utf-8")
    route = (ROOT / "frontend" / "app" / "api" / "proxy" / "[...path]" / "route.ts").read_text(encoding="utf-8")
    proxy = (ROOT / "frontend" / "lib" / "server" / "proxy.ts").read_text(encoding="utf-8")
    next_config = (ROOT / "frontend" / "next.config.ts").read_text(encoding="utf-8")
    env_example = (ROOT / "frontend" / ".env.example").read_text(encoding="utf-8")
    stream_hook = (ROOT / "frontend" / "lib" / "hooks" / "useBundleStream.ts").read_text(encoding="utf-8")

    assert "API_URL=\"$(gcloud run services describe" in ui_script
    assert "NEXT_PUBLIC_API_BASE" not in ui_script
    assert "API_BASE=\"${API_URL}\"" in ui_script
    assert "env.API_BASE" in proxy and "process.env" in proxy and 'export const dynamic = "force-dynamic"' in route
    assert "NEXT_PUBLIC_API_BASE" not in route and "NEXT_PUBLIC_API_BASE" not in proxy
    assert "rewrites" not in next_config
    assert "NEXT_PUBLIC_API_BASE" not in env_example
    assert "`/api/proxy/bundles/${encodeURIComponent(bundleId)}/stream`" in stream_hook


def test_api_is_private_and_only_the_ui_identity_may_invoke_it() -> None:
    api = (ROOT / "infra" / "deploy_api.sh").read_text(encoding="utf-8")
    ui = (ROOT / "infra" / "deploy_ui.sh").read_text(encoding="utf-8")
    bootstrap = (ROOT / "infra" / "bootstrap.sh").read_text(encoding="utf-8")
    route = (ROOT / "frontend" / "app" / "api" / "proxy" / "[...path]" / "route.ts").read_text(encoding="utf-8")
    proxy = (ROOT / "frontend" / "lib" / "server" / "proxy.ts").read_text(encoding="utf-8")

    # the API: no anonymous access, and it trusts the client-IP header only because only the UI can reach it
    assert "--no-allow-unauthenticated" in api
    assert "--allow-unauthenticated" not in api.replace("--no-allow-unauthenticated", "")
    assert 'CLIENT_IP_HEADER="x-cargoclear-client-ip"' in api
    # a binding left by the earlier PUBLIC deployment is removed explicitly
    assert 'remove-iam-policy-binding cargoclear-api' in api and '--member "allUsers"' in api
    # the UI: public front door, its own identity, invoker on the API, and told to send ID tokens
    assert 'UI_SERVICE_ACCOUNT="${UI_SERVICE_ACCOUNT:?' in ui
    assert '--service-account "${UI_SERVICE_ACCOUNT}"' in ui
    assert "add-iam-policy-binding cargoclear-api" in ui and "roles/run.invoker" in ui
    assert 'API_AUTH_MODE="google-id-token"' in ui
    assert "--allow-unauthenticated" in ui
    # the UI identity exists and holds no project role
    assert "cargoclear-ui-sa" in bootstrap
    # the proxy sends the header the API reads, and never forwards a browser-supplied copy of it
    assert 'CLIENT_IP_HEADER = "x-cargoclear-client-ip"' in proxy
    assert "google-id-token" in proxy and "metadata.google.internal" in proxy
    assert "export async function GET" in route and "export async function POST" in route
    assert "export async function PUT" not in route and "export async function DELETE" not in route


def test_runtime_identity_roles_include_firestore_without_hardcoded_project_email() -> None:
    roles = yaml.safe_load((ROOT / "infra" / "iam" / "roles.yaml").read_text(encoding="utf-8"))
    bootstrap = (ROOT / "infra" / "bootstrap.sh").read_text(encoding="utf-8")

    assert roles["service_account"] == "${RUNTIME_SERVICE_ACCOUNT}"
    assert "roles/datastore.user" in roles["roles"]
    assert "roles/datastore.user" in bootstrap
    # starting the tariff VECTOR_SEARCH is a query JOB: dataViewer alone cannot do it
    assert "roles/bigquery.dataViewer" in roles["roles"] and "roles/bigquery.jobUser" in roles["roles"]
    assert "roles/bigquery.jobUser" in bootstrap
    # the API runs no Cloud Run -> Cloud Run call; only the UI identity may invoke it, on that one service
    assert "roles/run.invoker" not in roles["roles"]
    assert roles["ui_service_account"] == "${UI_SERVICE_ACCOUNT}" and roles["ui_roles"] == []
    assert roles["ui_resource_bindings"] == [
        {"resource": "cloud-run-service/cargoclear-api", "role": "roles/run.invoker"}
    ]


def test_backend_image_copies_the_packaged_demo_fixtures_with_the_app() -> None:
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    packaged = ROOT / "backend" / "app" / "fixtures" / "case_c"

    assert "COPY app/ ./app/" in dockerfile
    assert {path.name for path in packaged.glob("*.pdf")} == {
        "commercial_invoice.pdf",
        "bill_of_lading.pdf",
        "packing_list.pdf",
        "mtc_pipe_test_cert.pdf",
    }


def test_model_ids_can_be_overridden_at_deploy_time_without_editing_the_script() -> None:
    script = (ROOT / "infra" / "deploy_api.sh").read_text(encoding="utf-8")

    assert 'GEMINI_LIVE_MODEL="${GEMINI_LIVE_MODEL:-gemini-2.5-flash}"' in script
    assert 'GEMINI_LIVE_LOCATION="${GEMINI_LIVE_LOCATION:-${REGION}}"' in script
    assert 'BQ_MODEL_EMBEDDING="${BQ_MODEL_EMBEDDING:-embedding_model}"' in script


def test_bigquery_setup_is_reproducible_and_never_defaults_the_embedding_model() -> None:
    script = (ROOT / "infra" / "bigquery" / "setup_tariff.sh").read_text(encoding="utf-8")

    # Google retires embedding models: the endpoint has to be chosen deliberately, with no stale default
    assert 'EMBEDDING_ENDPOINT="${EMBEDDING_ENDPOINT:?' in script
    assert 'PROJECT_ID="${PROJECT_ID:?' in script
    for step in ("mk --connection", "CREATE OR REPLACE MODEL", "TRUNCATE TABLE", "VECTOR_SEARCH", "roles/aiplatform.user"):
        assert step in script, step
    # the check runs the API's own query shape: destination pre-filter inside the base-table subquery
    assert "(SELECT * FROM \\`${TABLE}\\` WHERE destination_country = @dest)" in script


def test_frontend_image_does_not_run_as_root() -> None:
    dockerfile = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    runner = dockerfile[dockerfile.index("AS runner"):]

    assert "USER node" in runner
    assert runner.index("USER node") > runner.index("COPY --from=builder")
    assert "--chown=node:node" in runner


def test_reports_written_by_the_verification_scripts_are_git_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "preflight-report*.json" in ignored
    assert "live-e2e-report*.json" in ignored


def test_backend_image_carries_the_reference_tables_and_both_demo_cases() -> None:
    """The image copies app/ only: the curated tables and every sample PDF must live under it, or live mode starts without rules."""
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    app = ROOT / "backend" / "app"

    assert "COPY app/ ./app/" in dockerfile
    tables = {path.name for path in (app / "reference").glob("*.json")}
    assert tables == {"hs_rules.json", "specs.json", "duty_rates.json", "valuation_defaults.json", "exchange_rates.json", "anti_dumping.json",
                      "declaration_inputs.json"}
    assert {path.name for path in (app / "fixtures" / "case_d").glob("*.pdf")} == {
        "case_d_commercial_invoice.pdf", "case_d_bill_of_lading.pdf", "case_d_packing_list.pdf", "case_d_mtc_test_cert.pdf",
    }
    # the tables are source: no .gitignore pattern may swallow them (git itself is not needed: the CI image has none)
    import fnmatch

    patterns = [
        line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith(("#", "!"))
    ]
    for table in (app / "reference").glob("*.json"):
        relative = table.relative_to(ROOT).as_posix()
        hits = [
            p for p in patterns
            if fnmatch.fnmatch(table.name, p.rstrip("/")) or fnmatch.fnmatch(relative, p.lstrip("/").rstrip("/"))
        ]
        assert hits == [], f"{relative} is git-ignored by {hits}"
