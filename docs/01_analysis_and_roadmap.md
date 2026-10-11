# CargoClear implementation roadmap and current state

This roadmap distinguishes code verified locally from static configuration and work that needs an authorised cloud environment. It is not a claim that every product-spec aspiration is complete.

## Completed and locally verified

| Area | Status | Evidence |
|---|---|---|
| Case C browser journey | Complete | The current Playwright specs create a new demo bundle from `/`, analyze it, add the sample MTC, and inspect Reasoning Delta/Audit Chain. |
| Demo and live-mode separation | Complete | Demo endpoints require `APP_MODE=demo`; live mode disables fixture fallback and requires GCP services. |
| Backend lifecycle and audit chain | Complete | Unit/integration coverage exercises run state, reassessment, hash-chain verification, and SSE event contracts. |
| PDF preprocessing provenance | Complete with stated limitation | 200-DPI B&W extraction pages, confident quarter-turn orientation, split artifacts, document-scoped metadata persistence/retrieval, and original-PDF overlay mapping are implemented. |
| Frontend build integrity | Complete | Typecheck, lint, and production build pass in the verified local environment. |
| Cloud Run configuration guardrails | Statically validated | Scripts/configuration enforce a single API instance, runtime BFF URL flow, live mode, hidden docs, and a mandatory runtime identity. |
| Cloud Run deployment | Complete & Verified Live | Backend (`cargoclear-api`) and Frontend (`cargoclear-ui`) deployed in `asia-south1` via Cloud Build with BFF proxy routing. |
| BigQuery AHTN Grounding | Complete & Verified Live | `ahtn.master_tariff` and `embedding_model` (`text-embedding-004`) provisioned in `asia-south1`; vector search evaluates required documents. |
| Live extraction resilience | Complete & Verified Live | Multimodal extraction with Gemini 2.5 Flash on Vertex AI; `GEMINI_MAX_OUTPUT_TOKENS` tuned to 65,536 for complex trade documents. |
| Upload & Error UX feedback | Complete | Real-time batch upload progress (`current/total`) and prominent, responsive error diagnostics banner in Assessment panel. |

## Current product path

1. A user creates a bundle or starts a fresh Case C demo bundle.
2. Documents are stored and processed; extraction evidence has document/page provenance.
3. The pipeline computes deterministic and grounded assessment checks.
4. The UI receives status/iteration changes through same-origin BFF-proxied SSE.
5. A corrective document can trigger reassessment; the new iteration produces a Reasoning Delta and extends the audit chain.

## Partial work and known limitations

| Area | Current state | Follow-up |
|---|---|---|
| Deskew coordinate mapping | Detection is diagnostic; `deskew_applied` is false because no reversible transform is persisted. | Persist/apply a reversible deskew transform before claiming deskew-coordinate inversion. |
| Horizontal API scaling | Not supported: locks, rate limits, and SSE wakeups are process-local. | Design durable/distributed coordination before increasing Cloud Run API instances. |
| Playwright execution in restricted environments | Specs are current, but browser/port sandboxing may prevent execution. | Run in an environment with Playwright browsers and local server binding. |

## Deliberately deferred or out of scope

- Government portal submission, payment/duty calculation, and legal determination.
- Authentication and SSO.
- General horizontal scale-out of the API.
- Frontend inverse mapping for any future non-affine preprocessing beyond the supported rotation/source-page metadata.
- Browser test changes that hide environment failures by using canned bundle IDs or external services.

## Deployment readiness checklist

Static configuration currently requires all of the following before deployment is attempted:

- An authorised `PROJECT_ID` and `RUNTIME_SERVICE_ACCOUNT`.
- Deployer permission to act as that service account.
- Runtime roles for Vertex AI, scoped Storage access where possible, BigQuery read access, and Firestore (`roles/datastore.user`).
- API deployed first; UI deployment then discovers the actual API URL and sets server-only `API_BASE`.
- API held at one instance, with 300-second request timeout, no CPU throttling, and live mode/API docs configuration.

The checklist is not proof of a successful cloud deployment. Docker/image build, Cloud Run networking, IAM effectiveness, GCP resource availability, and live SSE behavior remain verification work requiring authorised access.
