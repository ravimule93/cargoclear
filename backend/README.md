# CargoClear Backend Engine

> **Google Cloud AI Builder Cup 2026** | Multimodal Customs Compliance & Deterministic Verification

The CargoClear backend is a high-performance, asynchronous Python service built on **FastAPI** and **Python 3.12**. It orchestrates multimodal document intelligence (Google Vertex AI Gemini 2.5 Flash), dense tariff vector search (Google BigQuery), deterministic metallurgical and trade compliance verification, and tamper-evident audit logging (Google Cloud KMS & Firestore).

---

## Architectural Principles

1. **Decision Support, Not Blind Automation**: CargoClear produces evidence-backed compliance assessments and indicative duty estimates with clear assumptions, designed to assist licensed Customs House Agents (CHAs) rather than silently filing declarations.
2. **Deterministic Rules Over Hallucinations**: LLMs extract document evidence, but **all legal, mathematical, and metallurgical checks are 100% deterministic**. An LLM never calculates duty or determines alloy qualification.
3. **Traceability & Grounding**: Every extracted fact links to its source document, page number, and bounding box coordinates ("What the model saw").
4. **Zero-LLM Recomputation**: Agent corrections re-execute deterministic rules instantly without re-calling the LLM, eliminating recurring token spend and latency.
5. **Defense-in-Depth Security**: Prompt injection guards, input gating, strict schema validation, and least-privilege IAM prevent malicious document tampering.

---

## Core Pipeline Architecture

```
                                    Raw PDFs
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │ 1. Preprocessing & Input Gating   │
                     │  • Auto-rotation & Deskewing      │
                     │  • Prompt-injection guard         │
                     │  • Visual rendering (PyMuPDF)     │
                     └─────────────────┬─────────────────┘
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │ 2. Multimodal Extraction Agent    │
                     │  • Gemini 2.5 Flash (Vertex AI)   │
                     │  • Structured Pydantic extraction │
                     │  • Confidence scores & coordinates│
                     └─────────────────┬─────────────────┘
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │ 3. BigQuery Vector Search         │
                     │  • Dense tariff embeddings (AHTN) │
                     │  • HS code candidate retrieval    │
                     │  • Duty rate & trade remedy lookup│
                     └─────────────────┬─────────────────┘
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │ 4. Deterministic Compliance Engine│
                     │  • HS Ch 72 Note 1 Alloy Check    │
                     │  • Carbon Equivalent (CEV) formula│
                     │  • Invoice 3-way arithmetic match │
                     │  • Country of Origin consistency  │
                     │  • Anti-dumping / remedy flags    │
                     └─────────────────┬─────────────────┘
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │ 5. Audit Chain & KMS Head Signing │
                     │  • SHA-256 hash-chained events    │
                     │  • Cloud KMS ECDSA P-256 signature│
                     │  • Declaration Pre-fill Pack (PDF)│
                     └───────────────────────────────────┘
```

---

## Detailed Pipeline Stages

### 1. Preprocessing & Document Vision
- **PyMuPDF (`fitz`) Integration**: Parses vector and raster PDF documents, generating normalized page images.
- **Orientation & Deskewing**: Reversible deskewing algorithms correct scanned skewed pages while keeping bounding box coordinate translations mathematically aligned to original pages.
- **Prompt Injection Defense**: Multi-layer inspection blocks prompt injection attempts embedded inside invoice descriptions or PDF metadata before payloads reach Gemini.

### 2. Multimodal Extraction Agent
- **Model**: `gemini-2.5-flash` deployed on Vertex AI (`asia-south1`).
- **Structured Schema Enforcement**: Extracts commercial invoice line items, bill of lading voyage and container details, packing list weights and heat numbers, and Mill Test Certificate chemical analysis.
- **Dual-Mode Operation**:
  - **Live Mode**: Calls Vertex AI Gemini 2.5 Flash with raw PDF page images.
  - **Demo Mode**: Loads pre-packaged, offline-deterministic fixtures (`Case C` and `Case D`) for zero-dependency local demonstrations.

### 3. BigQuery Vector Search & Tariff Grounding
- **Dataset**: `ahtn` (ASEAN Harmonized Tariff Nomenclature & Indian Customs Tariff Schedule).
- **Dense Retrieval**: Matches extracted product descriptions against 10,000+ tariff subheadings via BigQuery vector search using embeddings.
- **Trade Remedy Correlation**: Automatically cross-references declared origin and destination countries against anti-dumping and countervailing duty orders.

### 4. Deterministic Compliance & Metallurgy Engines
- **Alloy Qualification (HS Chapter 72 Note 1)**: Computes whether steel qualifies as alloy vs non-alloy based on exact chemical thresholds:
  $$\text{Cr} \ge 0.30\%,\; \text{Ni} \ge 0.30\%,\; \text{Mo} \ge 0.08\%,\; \text{Mn} \ge 1.65\%,\; \text{Si} \ge 0.60\%$$
- **Carbon Equivalent Value (CEV)**: Deterministically calculates weldability:
  $$\text{CEV} = \text{C} + \frac{\text{Mn}}{6} + \frac{\text{Cr} + \text{Mo} + \text{V}}{5} + \frac{\text{Ni} + \text{Cu}}{15}$$
- **Mechanical Properties Verification**: Verifies Tensile Strength, Yield Strength, and Yield/Tensile ratio against declared standard specifications (e.g. ASTM A106 Grade B, EN 10216-2).
- **Invoice 3-Way Reconciliation**:
  $$\text{Line Total} = \text{Quantity} \times \text{Unit Price}$$
  $$\text{CIF Value} = \text{FOB Subtotal} + \text{Freight} + \text{Insurance}$$
- **Heat Number Traceability**: Reconciles heat numbers across Mill Test Certificates and Packing Lists to prevent fraudulent substitution.

### 5. Tamper-Evident Audit Chain & KMS Signing
- **Hash-Chaining**: Every action (`BUNDLE_CREATED`, `DOCUMENTS_EXTRACTED`, `ASSESSMENT_COMPLETED`, `FIELD_CORRECTED`) records `parent_hash = SHA256(previous_event)`.
- **Cloud KMS Digital Signature**: The head hash of each completed iteration is signed using an asymmetric ECDSA P-256 key (`cargoclear/audit-head`) hosted in Google Cloud KMS.
- **Declaration Pre-Fill Pack**: Generates verifiable JSON and publication-grade printable PDFs with document citations and confidence indicators.

---

## Directory Structure

```
backend/
├── app/
│   ├── agents/          # Multimodal Gemini extraction agent and workflow orchestrators
│   ├── api/             # FastAPI routers (v1/bundles, v1/documents, v1/stream, v1/auth)
│   ├── core/            # Configuration, mode management (demo vs live), concurrency
│   ├── domain/          # Pydantic domain models, schemas, and error types
│   ├── fixtures/        # Packaged demo PDF bundles (Case C and Case D)
│   ├── gateway/         # Auth verification, rate limiting, and daily token budget
│   ├── reference/       # Curated compliance rules (HS codes, alloy thresholds, duty rates)
│   ├── repo/            # BigQuery, Firestore leases, and GCS storage repositories
│   ├── services/        # Metallurgy, arithmetic, audit chaining, and KMS signing engines
│   └── main.py          # FastAPI application entrypoint and middleware assembly
├── tests/
│   ├── unit/            # Unit test suite (metallurgy, arithmetic, contract tests)
│   └── integration/     # Integration tests (FastAPI routes, streaming, corrections)
├── Dockerfile           # Multi-stage production container image with Poppler
├── requirements.txt     # Locked production dependencies
└── requirements-dev.txt # Development and testing dependencies
```

---

## Local Setup & Development

### 1. Prerequisites
- Python 3.12+
- Virtual environment (`venv` or `uv`)
- Poppler (for PDF page rendering)

### 2. Environment Setup
```bash
cd backend
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows PowerShell:
.venv\Scripts\Activate.ps1

pip install -r requirements-dev.txt
```

### 3. Run Development Server
```bash
# Demo Mode (zero GCP credentials needed)
APP_MODE=demo AUTH_ENABLED=true uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
```

---

## Testing & Quality Assurance

CargoClear maintains strict automated test coverage across all domain and compliance engines:

```bash
# Run all unit and integration tests:
python -m pytest tests/unit tests/integration -q

# Run with test coverage report:
python -m pytest tests/unit tests/integration --cov=app --cov-report=term-missing
```

**Test Suite Health**:
- **8,043** total statements tested
- **95%+** overall codebase coverage
- **100%** passing rate on deployment contracts and metallurgical checks

---

## Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `APP_MODE` | `live` | `demo` uses local synthetic fixtures; `live` connects to GCP. |
| `PROJECT_ID` | Required | Target Google Cloud Project ID. |
| `REGION` | `asia-south1` | Cloud Run and Vertex AI region. |
| `RUNTIME_SERVICE_ACCOUNT`| Required | Cloud Run service identity with least-privilege IAM. |
| `GEMINI_LIVE_MODEL` | `gemini-2.5-flash` | Multimodal foundation model on Vertex AI. |
| `DAILY_TOKEN_BUDGET` | `5000000` | Maximum token consumption allowed per UTC day. |
| `RAW_BUCKET` | `cargoclear-raw-pdfs` | Cloud Storage bucket storing uploaded trade PDFs. |
| `FIRESTORE_DATABASE` | `(default)` | Firestore database storing bundles, leases, and audit logs. |
| `BQ_DATASET` | `ahtn` | BigQuery dataset containing tariff schedules and embeddings. |
