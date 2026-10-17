# Prompt: make the demo path's removal from the live app complete and permanent, then test CargoClear end to end

Paste everything below the line into a fresh Claude Code session opened in this repository (branch `improvement-plan`, merge of `origin/development` included).

---

You are working in the CargoClear repository (FastAPI backend in `backend/`, Next.js 15 UI in `frontend/`, deploy scripts in `infra/`, runbooks in `docs/`). Read `Handoff.md`, `docs/CLAIMS.md` and `docs/HOW_TO_RUN_AND_DEMO.md` first.

## Background

The product has two modes, chosen by `APP_MODE` (`backend/app/core/config.py`, default `demo`):

- **demo**: synthetic fixtures keyed on file names, mock sessions (`mock-jwt-<email>-<ROLE>` tokens), a "Start Case C / Case D demo" pair of buttons, a sample-certificate button, three one-click demo accounts. It is what the Playwright journeys and local runs use.
- **live**: real Gemini extraction, real Google sign-in. The deployed site (https://cargoclear-app.web.app, Cloud Run `cargoclear-ui` and `cargoclear-api`, project `cargoclear-hackathon`, region `asia-south1`) runs live.

Commit `7650346` ("improv 2", PR #12) took the demo path out of the live app: the Google callback no longer mints a `mock-jwt` session, the home page hides demo accounts and demo buttons unless `/meta` says `app_mode: "demo"`, and the backend refuses mock tokens outside demo mode (`backend/app/gateway/auth.py`). That removal is incomplete and not protected by tests. Known gaps in the merged tree:

1. `backend/app/api/v1/demo.py`: the three demo routes (`POST /demo/case-c`, `POST /demo/case-d`, `GET /demo/case-c/mtc`) now depend on `get_current_user`, which runs before `_require_demo_mode()`. In live mode an anonymous caller gets 401 instead of 404, so the routes reveal they exist. `backend/tests/unit/test_demo.py::test_404_when_app_mode_is_live` and `::test_case_d_is_demo_only` fail for this reason.
2. `frontend/app/auth/signin/page.tsx` still shows "Quick demo presets (1-click sign in)" in every mode and writes a `mock-jwt` cookie (`handleQuickDemoLogin`).
3. `mock-jwt-` strings are built in seven frontend places (`app/page.tsx` x4, `app/workbench/[bundleId]/page.tsx` x2, `app/auth/signin/page.tsx`) and parsed again in `lib/hooks/useMeta.ts`. Only the home page checks the mode.
4. `APP_MODE` defaults to `demo`. A live deployment that loses the variable would silently serve fixtures and mock sessions. `infra/deploy_api.sh` sets `APP_MODE=live`, but nothing checks the result after a deploy.
5. `scripts/verify_live_domain.py` hard-codes a bundle id and sends a `mock-jwt` cookie to the live site, which is the opposite of what the live app should accept.
6. There is a work-in-progress set aside in `git stash@{0}` ("web UX overhaul") that already centralises the cookie code in `frontend/lib/session.ts` (`demoSignIn` refuses unless `/meta` reports demo) and has specs `frontend/tests/session.unit.spec.ts` and `frontend/tests/dashboard_journey.spec.ts` (signed-out landing with `page.route` for `/api/proxy/meta`). Read it without touching the stash: tracked changes with `git stash show -p stash@{0}`, new files with `git show 'stash@{0}^3:frontend/lib/session.ts'` (same form for the two specs). Reuse the ideas; do not pop or drop the stash.

## Invariants to enforce (each needs a test that fails today or would fail if it regressed)

- I1. In live mode nothing in the browser or the API can give anyone a session without a verified Google ID token: no demo account, no mock cookie, no mock header, no password route.
- I2. The demo routes do not exist in live mode: 404 for every caller, signed in or not, before authentication runs.
- I3. Mock tokens are created and read in one place per side (one frontend module, one backend path), and the frontend module refuses to write one unless `/meta` says `app_mode: "demo"`.
- I4. Demo mode keeps working unchanged: the Case C and Case D buttons, the sample certificate, the demo accounts, fixture extraction. Every existing journey in `frontend/tests` still passes against a demo backend.
- I5. A live deployment that comes up in demo mode is detected, not served: add a post-deploy assertion (`/meta` and `/version` report `app_mode: "live"`) to the deploy flow or its verification script, and make the failure loud.

## Work

1. Backend: make the demo-mode check the first dependency of the demo router (before authentication), so live answers 404 to everyone. Fix the two failing demo tests; add tests for all three routes in live mode, anonymous and authenticated; add a test that a `mock-jwt` token in `Authorization`, in `X-CargoClear-User-Token` and in a cookie is never a user in live mode.
2. Frontend: one session module; gate the sign-in page's presets on `/meta`; remove the other copies; unit-test the module (guard, token round trip, cookie parse). Keep the demo accounts' emails as they are.
3. Ops: update `scripts/verify_live_domain.py` and `scripts/verify_sso_live.py` so they check that the live site exposes no demo surface instead of using a mock cookie; add the post-deploy mode assertion (I5). Mention the new check in `docs/GCP_VERIFICATION.md` and `docs/DEPLOYMENT_GUIDE_GCP.md`.
4. Do not add numbers or superlatives to `README.md`, `Product.md`, the runbooks or any UI copy: `backend/tests/unit/test_claims.py` scans them. If a feature changes what is true, update the rows in `docs/CLAIMS.md` and its header counts in the same change.

## End-to-end test plan (run it, report what ran and what did not)

A. Static: `cd backend && .venv/bin/python -m pytest tests/unit tests/integration -q --no-cov`; `cd frontend && npx tsc --noEmit && npm run test:unit && npm run build`. 14 backend unit tests fail on the merged branch and the merge did not introduce any of them (the two demo ones are in scope; the rest are older tests that expect the pre-hardening "Bundle 'x' not found." message and need a decision, not a silent edit: list them and propose test or code changes).

B. Demo mode, whole journey, locally. A long-running backend of the owner's may already hold port 8080 with older code: do not stop it. Start your own: `cd backend && APP_MODE=demo RATE_LIMIT_WRITES_PER_MINUTE=0 RATE_LIMIT_RUNS_PER_MINUTE=0 MAX_CONCURRENT_RUNS=0 .venv/bin/uvicorn app.main:app --port 8081`, then `cd frontend && API_BASE=http://localhost:8081 npm run dev`. Run the browser suite against those two servers (the repo config starts and reuses servers on 8080 and 3000; use a config outside the repo that imports it, points its `webServer` entries at 8081 and 3000, and run with `NODE_PATH=<repo>/frontend/node_modules`). `frontend/public/pdf.worker.min.mjs` is tracked but may be older than the installed pdfjs-dist: if the viewer reports an API/Worker version mismatch run `node scripts/copy-pdf-worker.mjs`, and put the file back afterwards (`cp` from a backup you made first) so it does not appear in the diff. Then run the walkthrough recorder with `DEMO_VIDEO=off DEMO_BASE_URL=http://localhost:3000 DEMO_OUT_DIR=<scratch> npx playwright test -c playwright.demo.config.ts` and look at the screenshots.

C. Live mode, locally, without Google Cloud: backend tests use `monkeypatch` on `settings` (see `backend/tests/unit/test_auth_sso.py`); the UI can be driven in live mode by fulfilling `/api/proxy/meta` with `page.route` (`app_mode: "live"`, `auth.enabled: true`, `user: null`). Check: the home and sign-in pages contain no demo account, no demo button, no "demo" wording; a `mock-jwt` cookie set in the browser does not make `meta.user` appear.

D. Deployed site, read-only, no sign-in (both https://cargoclear-app.web.app and the direct Cloud Run UI URL from `gcloud run services describe cargoclear-ui --project cargoclear-hackathon --region asia-south1 --format='value(status.url)'`):
   - `GET /api/proxy/meta` reports `app_mode: "live"` and `user: null`.
   - `POST /api/proxy/demo/case-c`, `POST /api/proxy/demo/case-d`, `GET /api/proxy/demo/case-c/mtc` are 404 (not 401, not 405 from a different layer: say which layer answered).
   - With `Cookie: __session=mock-jwt-demo-cha@customs.com-LICENSED_CHA` (and again with `cargoclear_session_token`): `/api/proxy/meta` has `user: null` and `GET /api/proxy/bundles` is 401.
   - The HTML of `/` and `/auth/signin?tab=signin` contains none of: "demo", "1-Click", "mock-jwt", "Cloud Run".
   - `/api/auth/signin/google` answers 307 to `accounts.google.com`.
   Use `gcloud` only if the owner has asked for deployment work in this session, and never deploy as part of this prompt.

E. Signed-in live journey: this needs a human (credentials are never typed by the agent). Prepare a checklist for the owner: sign in with Google; "Start a new clearance" with `fixtures/case_c/*.pdf` and destination Singapore; run the analysis; expect `MISSING_EVIDENCE` for the mill test certificate; upload `fixtures/case_c/mtc_pipe_test_cert.pdf`; expect `COMPLIANT_FOR_SUBMISSION`; correct a certificate cell on `fixtures/case_d/*` (India), recompute, download the pre-fill; open the activity log and check the chain verifies; sign out. This spends model tokens against `DAILY_TOKEN_BUDGET`: say so before anyone runs it. `scripts/live_e2e_hosted.py` and `docs/GCP_VERIFICATION.md` hold the scripted version. Any time or accuracy figure from a live run goes through `scripts/measured_results.py ingest` and is quoted only from `docs/MEASURED_RESULTS.md`.

## Rules for this session

- Do not run git commands that change anything: no add, commit, stash, checkout, reset, push, branch or merge. Read-only git is fine. Leave every change in the working tree for the owner to review and commit. Keep `.gitignore` current for any new generated file.
- Do not deploy, and do not change IAM, secrets or Cloud Run settings.
- Do not sign in on the owner's behalf, create accounts, or type credentials anywhere.
- Report, in this order: what you changed (files), which tests you added and that each fails without its fix, the result of A to D with real output, the checklist for E, and anything you could not verify.
