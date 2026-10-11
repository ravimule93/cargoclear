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


def test_api_deploy_is_single_instance_and_fails_closed_without_runtime_identity() -> None:
    script = (ROOT / "infra" / "deploy_api.sh").read_text(encoding="utf-8")

    assert 'RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:?' in script
    assert "--service-account \"${RUNTIME_SERVICE_ACCOUNT}\"" in script
    assert "--max-instances 1" in script
    assert "--concurrency 80" in script
    assert "--timeout 300" in script
    assert "--no-cpu-throttling" in script
    assert 'APP_MODE="live"' in script
    assert 'ENABLE_API_DOCS="false"' in script


def test_ui_uses_a_runtime_server_only_api_url_for_proxy_and_sse() -> None:
    ui_script = (ROOT / "infra" / "deploy_ui.sh").read_text(encoding="utf-8")
    proxy = (ROOT / "frontend" / "app" / "api" / "proxy" / "[...path]" / "route.ts").read_text(encoding="utf-8")
    next_config = (ROOT / "frontend" / "next.config.ts").read_text(encoding="utf-8")
    env_example = (ROOT / "frontend" / ".env.example").read_text(encoding="utf-8")
    sse = (ROOT / "frontend" / "lib" / "sse.ts").read_text(encoding="utf-8")

    assert "API_URL=\"$(gcloud run services describe" in ui_script
    assert "NEXT_PUBLIC_API_BASE" not in ui_script
    assert "API_BASE=\"${API_URL}\"" in ui_script
    assert "process.env.API_BASE" in proxy and 'export const dynamic = "force-dynamic"' in proxy
    assert "NEXT_PUBLIC_API_BASE" not in proxy
    assert "rewrites" not in next_config
    assert "NEXT_PUBLIC_API_BASE" not in env_example
    assert "`/api/proxy/bundles/${bundleId}/stream`" in sse


def test_runtime_identity_roles_include_firestore_without_hardcoded_project_email() -> None:
    roles = yaml.safe_load((ROOT / "infra" / "iam" / "roles.yaml").read_text(encoding="utf-8"))
    bootstrap = (ROOT / "infra" / "bootstrap.sh").read_text(encoding="utf-8")

    assert roles["service_account"] == "${RUNTIME_SERVICE_ACCOUNT}"
    assert "roles/datastore.user" in roles["roles"]
    assert "roles/datastore.user" in bootstrap
    assert "roles/run.invoker" not in roles["roles"]


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
