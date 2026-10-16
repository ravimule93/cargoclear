# Release evidence

Every hosted CargoClear claim must identify the code and runtime configuration that produced it. Record the immutable release SHA, ISO-8601 release timestamp, API/UI revision IDs, deployment URLs, `GET /version` output, source-data fingerprints, and CI/preflight/hosted-E2E report locations.

`GET /version` exposes only non-sensitive release metadata; it is not a dependency health check. `infra/deploy_api.sh` rejects a release without `RELEASE_SHA` and `RELEASE_TIMESTAMP`. In Cloud Build, supply `_RELEASE_SHA` and `_RELEASE_TIMESTAMP` explicitly.
