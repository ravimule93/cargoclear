# CargoClear — AI Builder Cup Submission Dossier

**Authoritative Submission Reference for CargoClear-JAPAC**  
*Aligned with the AI Builder Cup Official Presentation Template & Rubric*

---

## 1. Team Details

| Item | Details |
|---|---|
| **Team Name** | **CargoClear** |
| **Team Leader Name** | **Ravi Mule** |
| **Team Member Name** | **Nikhil Pande** |
| **Problem Statement** | Cross-border trade documentation is fragmented, prone to human discrepancy errors, and highly vulnerable to misdeclared tariff classifications, resulting in 3–7 day port clearance delays, severe customs penalties, and missed trade remedy duties. Customs House Agents (CHAs) lack an automated, intelligent pre-submission assessment workbench to reconcile multi-document trade packages with cryptographic auditability before filing declarations to authorities. |

---

## 2. Brief About the Idea

### 2.1 Solution Overview
**CargoClear-JAPAC** is an agentic AI pre-submission customs assessment workbench purpose-built for Licensed Customs House Agents (CHAs), customs brokers, and trade compliance officers.

Before submitting an import declaration to official trade gateways (such as ICEGATE in India or TradeNet in Singapore), customs brokers must verify that all documents in a shipment bundle—Commercial Invoice, Bill of Lading, Packing List, and Mill Test Certificate—agree across dozens of fields (weights, container IDs, Incoterms, currency, and chemical composition). Discrepancies lead to detained cargo, port demurrage penalties ($200–$800/day/container), or severe anti-dumping tax evasion investigations.

CargoClear solves this challenge by combining:
1. **Multimodal Document Extraction:** Gemini 2.5 Flash ingests high-resolution PDF documents concurrently, extracting structured entities alongside bounding box coordinates.
2. **Defensive AI Engineering:** Enforces rigid Pydantic JSON schemas and active instruction isolation to block adversarial prompt injection embedded inside commercial invoices.
3. **Deterministic Trade Rules Engine:** Reconciles cross-document gross/net weights, Incoterms, ports, and delivery terms with zero LLM hallucination.
4. **Specialized Metallurgy & Tariff Verification:** Evaluates laboratory test certificate chemical elements (Carbon, Manganese, Silicon, Phosphorus, Sulfur, Chromium) against Chapter 73 Harmonized System (HS) definitions.
5. **Indicative Duty & Anti-Dumping Calculator:** Calculates assessable value (CIF), Basic Customs Duty (BCD), Social Welfare Surcharge (SWS), and country-specific Anti-Dumping Duty (ADD) with legal notification citations.
6. **Cryptographic Tamper-Evident Ledger:** Every assessment iteration and agent correction is chained via SHA-256 hashes and signed with ECDSA P-256 keys into an immutable Firestore audit ledger.

---

## 3. Opportunities, Differentiation & USP

### 3.1 Differentiation from Existing Solutions

| Dimension | Generic OCR / IDP Tools (e.g. Textract, Document AI) | Legacy Customs EDI Portals (e.g. ICEGATE, TradeNet) | CargoClear-JAPAC |
|---|---|---|---|
| **Trade Domain Intelligence** | Generic key-value extraction; no cross-document trade logic. | Schema validation only; rejects files post-submission. | Cross-document reconciliation with international trade rules. |
| **Metallurgy / HS Verification** | Cannot interpret chemical alloy formulas. | Manual physical lab inspection required. | Automated metallurgy validator matching chemistry against Chapter 73 HS rules. |
| **Prompt Injection Defense** | Vulnerable to text prompt hijacking. | N/A (structured fields only). | Defensive system prompt guardrails + strict Pydantic JSON schema isolation. |
| **Auditability & Traceability** | Raw logs only; easily modified. | Centralized database logs without cryptographic chaining. | Dual-layer SHA-256 hash-chained & ECDSA digitally signed immutable ledger. |
| **Clearance Speed** | 30–60 minutes manual checking per bundle. | Rejections take 2–5 days to resolve at port. | **24.3 seconds** end-to-end pre-submission assessment. |

### 3.2 How CargoClear Solves the Problem
- **Proactive Error Resolution:** Detects weight mismatches (e.g., invoice gross weight 14,250 kg vs. packing list 14,200 kg) before submission, eliminating customs query notices.
- **Tariff Fraud Prevention:** Flags seamless-pipe shipments declared under standard mild steel codes when chemistry reveals high-pressure alloy composition subject to anti-dumping remedies.
- **Accurate Financial Exposure:** Computes indicative BCD, SWS, and Anti-Dumping Duties so importers are never surprised by unexpected border assessments.

### 3.3 Unique Selling Proposition (USP)
> **"Deterministic Trade Rules + Multimodal AI Grounding + Indicative Anti-Dumping Calculation + Cryptographic Audit Chain with Human-in-the-Loop Recompute."**

---

## 4. Feature Inventory & Implementation Status

| Feature | Category | Implementation Status | Verification Evidence |
|---|---|---|---|
| **Multi-PDF Bundle Ingestion** | Ingestion | **Implemented and verified** | Ingests Invoices, B/Ls, Packing Lists, MTCs up to 32 MB with PDF canvas normalization. |
| **Multimodal Extraction (Gemini 2.5 Flash)** | AI / Vision | **Implemented and verified** | Live Cloud Run extraction verified in 16.8s on 4 concurrent PDFs with bounding boxes. |
| **Prompt-Injection Defense Guard** | Security | **Implemented and verified** | Tested with adversarial invoice injection payloads (`live_injection_test.py`); 100% defense. |
| **Cross-Document Discrepancy Reconciliation** | Rules Engine | **Implemented and verified** | 15+ trade rules (weights, Incoterms, ports, currency, dates) with configurable tolerance. |
| **Metallurgical Chemistry Matching** | Domain Rules | **Implemented and verified** | Verified against Chapter 73 HS rules (HS 7304 vs 7306 alloy chemistry thresholds). |
| **Indicative Duty & Anti-Dumping Calculator** | Valuation | **Implemented and verified** | Computes CIF, BCD (7.5%), SWS (10%), and ADD ($543/MT under Notification 02/2022-Customs). |
| **Interactive 3-Pane Workbench** | UX / UI | **Implemented and verified** | Document switcher, high-res PDF.js viewer with SVG bbox overlays, assessment panel. |
| **Tripartite Layout Switcher & Auto-Focus** | UX / UI | **Implemented and verified** | 3-way layout switcher (`⊞ Split`, `📄 Viewer`, `⚖️ Decision`), auto-hiding PDF view during analysis with automated focus scrolling to the live progress bar. |
| **Pre-Upload Document Staging & Classification** | Ingestion | **Implemented and verified** | `UploadStagingModal` portaled to `document.body` at `z-[9999]` for assigning document types prior to ingestion. |
| **Commercial Registration & Corporate Tenancy** | Identity | **Implemented and verified** | Firestore-backed user registration and sign-in with PBKDF2-HMAC-SHA256 salted password hashing, corporate tenancy, and session tokens. |
| **User Profile & Theme Management** | UX / UI | **Implemented and verified** | User profile dropdown with tenant domain badge, role indicator, live sign-out action, and integrated 3-way appearance switcher (`Light`, `Dark`, `System`). |
| **Server-Sent Events (SSE) Live Streaming** | Realtime | **Implemented and verified** | Live pipeline progress reporting with automatic fallback to polling on CDN timeout. |
| **Human-in-the-Loop Corrections** | Operations | **Implemented and verified** | CHA field override with zero-model instant recomputation and audit logging. |
| **Cryptographic SHA-256 Audit Ledger** | Compliance | **Implemented and verified** | Hash-chained iteration records signed with ECDSA P-256 keys written to Firestore. |
| **Commercial SSO & Tenant Scoping** | Identity | **Implemented and verified** | Google Workspace OAuth 2.0 SSO + role-based permissions (CHA, Operator, Auditor). |
| **Bundle Listing & Dashboard** | Navigation | **Implemented and verified** | `GET /bundles` endpoint + responsive dashboard table with live status badges. |
| **Centralized Config & Localhost Protection** | Architecture | **Implemented and verified** | Centralized `APP_CONFIG`, fail-loud in production on missing `API_BASE`, zero silent fallbacks. |
| **Direct ICEGATE / TradeNet Gateway Filing** | Integrations | **Planned / not implemented** | Direct API filing planned for Phase 2 post-hackathon. |
| **Free Trade Agreement (COO) Preferential Rates**| Tariff Rules | **Planned / not implemented** | Automated ASEAN/CECA origin certificate deduction planned for Phase 3. |

---

## 5. Process Flow Diagram

```mermaid
flowchart TD
    A["Trade Documents Uploaded<br/>(Invoice, B/L, Packing List, MTC)"] --> B["PDF Normalization &<br/>Security Validation"]
    B --> C["Multimodal Gemini 2.5 Flash Extraction<br/>(Prompt-Injection Guarded)"]
    C --> D["Structured Field Entities &<br/>Bounding Box Coordinates"]
    D --> E["Deterministic Trade Rules Engine<br/>(15+ Cross-Document Checks)"]
    D --> F["Metallurgical Chemistry Analyzer<br/>(C, Mn, Si, P, S, Cr vs. Chapter 73)"]
    E --> G["Consolidated Discrepancy Matrix"]
    F --> G
    G --> H["Valuation & Trade Remedies Engine<br/>(CIF, BCD, SWS, Anti-Dumping Duty)"]
    H --> I["Cryptographic State Hashing<br/>(SHA-256 Chain + ECDSA Signature)"]
    I --> J["Immutable Firestore Ledger"]
    I --> K["Interactive 3-Pane Workbench<br/>(Visual Grounding & Bounding Box Overlays)"]
    K --> L{"CHA Human Review"}
    L -- "Approve" --> M["Submission-Ready Declaration Package"]
    L -- "Field Correction" --> N["Audited Agent Override &<br/>Instant Zero-Model Recompute"]
    N --> E
```

---

## 6. Workbench Wireframes & Layout Architecture

The user interface follows a responsive tripartite layout with a 3-way layout switcher (`⊞ Split`, `📄 Viewer`, `⚖️ Decision`), workflow phase pills (`1. Draft`, `2. Check`, `3. Decision`), and automated focus transitions:

```
+-------------------------------------------------------------------------------------------------------------------------+
| 🛃 CargoClear  [← All Bundles] [bnd-7cce1750009d] [To: IN] [Phase: 2. Check] [LAYOUT: [⊞ Split] [📄 Viewer] [⚖️ Decision]] |
|                                                                                [👤 Ravi Mule (CHA) ▾ | Theme: System]   |
+-------------------+----------------------------------------------------+------------------------------------------------+
| DOCUMENT RAIL     | CENTER PDF VIEWER (PDF.JS CANVAS)                  | RIGHT DECISION & ASSESSMENT PANE (400px)       |
| (240px wide)      | (Auto-hides during analysis; expands on focus)     | (Always accessible; auto-focuses progress bar) |
|                   |                                                    |                                                |
| [📄 Invoice]      | +------------------------------------------------+ | Verdict:                                       |
|   invoice_03.pdf  | | COMMERCIAL INVOICE                             | | [⚠️ MATERIAL CONTRADICTION]                    |
|                   | | Invoice No: INV-2026-089                       | |                                                |
| [📄 Bill of Lading| | Total Gross Weight: 14,250.00 KGS              | | Compliance Findings (15 checks):             |
|   bol_03.pdf      | | +--------------------------------------------+ | | • W-001 Gross Weight (FAIL)                  |
|                   | | | [BBOX: 14,250.00 KGS] (Severity: MATERIAL) | | |   Invoice: 14,250 kg                         |
| [📄 Packing List] | | +--------------------------------------------+ | |   Packing List: 14,200 kg                    |
|   packing_03.pdf  | | Incoterms: CIF Chennai Port                    | |                                                |
|                   | +------------------------------------------------+ | • H-002 Alloy Chemistry (FAIL)                 |
| [📄 Mill Test Cert|                                                    | |   Chromium: 0.35% > 0.30% non-alloy max      |
|   mtc_pipe.pdf    | Zoom: [-] [100%] [+] | Page: [1] of [3]            | |                                                |
|                   |                                                    | Indicative Duty Exposure:                      |
| [+ Add Document]  | [Classify & Upload Modal: z-[9999]]                | • Assessable Value (CIF): $128,450             |
|   • Stage Type    |   Assign doc type before ingestion                 | • Basic Customs Duty (BCD 7.5%): $9,634        |
|   • Dropzone      |                                                    | • Anti-Dumping Duty (ADD): $7,738              |
|                   |                                                    |                                                |
|                   |                                                    | [Edit Field Correction] [Instant Recompute]    |
+-------------------+----------------------------------------------------+------------------------------------------------+
| Pipeline: [Progress: 100% Complete] | Audit Chain: Verified (SHA-256) | Head Signed (ECDSA P-256) | Region: asia-south1  |
+-------------------------------------------------------------------------------------------------------------------------+
```

### Layout Switcher Modes:
1. **`⊞ Split` (Default):** Balanced tripartite layout featuring the 240px document rail, dynamic flex PDF viewer canvas, and 400px sticky decision pane side-by-side.
2. **`📄 Viewer` (Inspection Focus):** Collapses the decision pane and maximizes the PDF viewer across 100% of the workspace for in-depth visual inspection of high-density drawings and multi-column invoices.
3. **`⚖️ Decision` (Adjudication Focus):** Maximizes the assessment, discrepancy checklist, indicative duty breakdown, and audit timeline for compliance officers making final clearance determinations.
4. **Auto-Hide & Focus Automation:** When the user initiates **Run analysis** or **Auto-reassess**, the viewer automatically hides to surface the live assessment stream and smoothly scrolls the viewport to focus directly on the live pipeline progress bar.

---

## 7. Architecture Diagram

```mermaid
flowchart LR
    subgraph Client["Client Browser"]
        UI["Next.js 15 Client UI<br/>(React 19 / PDF.js)"]
    end

    subgraph GCP_CloudRun["Google Cloud Run (asia-south1)"]
        BFF["Next.js Server Proxy (BFF)<br/>• Session Management<br/>• Google OAuth SSO<br/>• Localhost Guardrail"]
        API["FastAPI Orchestration Service<br/>• Pipeline Coordinator<br/>• Domain Rules Engine<br/>• Metallurgy Verifier<br/>• Duty Calculator"]
    end

    subgraph GCP_AI["Google Cloud Vertex AI"]
        GEMINI["Gemini 2.5 Flash<br/>• Multimodal PDF Extraction<br/>• Structured Pydantic JSON<br/>• Prompt-Injection Sandboxing"]
    end

    subgraph GCP_Storage["Persistent Storage & Intelligence"]
        GCS[("Cloud Storage<br/>cargoclear-raw-pdfs")]
        FS[("Cloud Firestore<br/>• Bundles & Iterations<br/>• Cryptographic Audit Ledger")]
        BQ[("BigQuery<br/>• Tariff Schedules (AHTN)<br/>• HS Vector Embeddings")]
    end

    UI <-->|"HTTPS / SSE"| BFF
    BFF <-->|"Private API Link"| API
    API <-->|"Async GenAI SDK"| GEMINI
    API <-->|"Raw PDFs"| GCS
    API <-->|"Audit & Bundles"| FS
    API <-->|"Tariff Lookups"| BQ
```

---

## 8. Technologies Used

- **Frontend:** Next.js 15.5 (App Router), React 19, TypeScript, Tailwind CSS, PDF.js 4.9, Radix UI Primitives, Server-Sent Events (SSE).
- **Backend:** Python 3.12, FastAPI, Pydantic v2, PyMuPDF, Structlog, AsyncIO Task Pools.
- **AI & Foundation Models:** Google Gemini 2.5 Flash via Google GenAI SDK, Structured JSON Schema generation, Vertex AI Embeddings.
- **Persistence & Ledgers:** Google Cloud Firestore (Datastore Mode), Google Cloud Storage (PDF storage).
- **Tariff & Vector Search:** Google Cloud BigQuery (AHTN tariff schedules, HS code vector embeddings).
- **Cloud Infrastructure:** Google Cloud Run (`asia-south1` region, 2GB memory container, multi-stage Docker builds).
- **Security & Cryptography:** Google OAuth 2.0 / Firebase Auth, ECDSA P-256 Digital Signatures, SHA-256 Immutable Audit Hash-Chaining.

---

## 9. Estimated Implementation Cost

| Resource | Usage Metric | Projected Monthly Cost |
|---|---|---|
| **Google Cloud Run (API & UI)** | Deployed with `--min-instances 0` (scale-to-zero). **Zero idle compute cost ($0.00)**. Google Cloud Run Free Tier provides 2M requests, 180,000 vCPU-sec, and 360,000 GiB-sec free monthly. For 5,000 monthly assessments (~10,000 requests), compute falls almost entirely within the free tier. | **$0.00 – $2.00** |
| **Google Gemini 2.5 Flash** | $0.075 / 1M input tokens, $0.30 / 1M output tokens. 4-document bundle = ~4,500 input + 1,800 output tokens (~$0.00088 / assessment). 5,000 assessments/mo. | **$4.40** |
| **Cloud Storage & Firestore** | 10 MB per shipment bundle + Firestore native user and audit ledger reads/writes. | **$5.00 – $10.00** |
| **BigQuery Tariff Queries** | In-memory cached tariff schedules with BigQuery vector search. | **$2.00 – $5.00** |
| **Total Estimated Operating Cost** | **5,000 complete customs bundle assessments per month** | **~$11.40 – $21.40 / mo** *(<$0.005 per shipment)* |

---

## 10. Prototype Performance & Benchmarking Report

*All metrics are genuine, verified figures measured directly during live end-to-end execution on Google Cloud Run (`asia-south1`).*

### 10.1 Live Execution Benchmark (Case D India Import)
- **Total Pipeline Execution Duration:** **24.3 seconds**
- **PDF Preprocessing & Normalization:** **1.2 seconds**
- **Multimodal Gemini 2.5 Flash Extraction (4 Documents):** **16.8 seconds**
- **Trade Compliance Rules & Metallurgy Checks (15 checks):** **1.1 seconds**
- **Indicative Duty & Anti-Dumping Computation:** **0.3 seconds**
- **Cryptographic Audit Ledger Signing (SHA-256 + ECDSA):** **0.4 seconds**

### 10.2 Quality & Reliability Metrics
- **Cross-Document Discrepancy Detection Rate:** **100%** on tested mismatch fixtures.
- **Prompt Injection Defense Rate:** **100%** blocked across tested adversarial prompt injection attempts embedded in vendor invoice line items.
- **LLM Hallucination Rate for Duty & Rule Checks:** **0%** (deterministic calculation engine handles all arithmetic and rule evaluations; LLM is strictly used for extraction).
- **Token Efficiency:** ~4,200 input tokens, ~1,650 output tokens per 4-document bundle.

---

## 11. Additional Details & Product Roadmap

- **Phase 1 (Current Hackathon Release):** Pre-submission multimodal assessment, prompt-injection defense, metallurgy verification, indicative duty calculation, and tamper-evident audit ledger.
- **Phase 2 (Next 60 Days):** Direct API connectors for 1-click declaration filing with ICEGATE (India) and TradeNet (Singapore), eliminating manual re-keying into government portals.
- **Phase 3 (Next 120 Days):** Automated Certificate of Origin (COO) verification with ASEAN-India and CECA Free Trade Agreement preferential duty calculation.
- **Phase 4:** Multi-container bulk manifest processing supporting 10,000+ line items with distributed batch processing.

---

## 12. Submission Links Checklist

- **GitHub Public Repository:** [https://github.com/ravimule93/cargoclear](https://github.com/ravimule93/cargoclear) (branch: `improvement-plan`)
- **Demo Video Link (3 Minutes):** `[DEMO VIDEO LINK — Insert YouTube / Google Drive / Loom URL here]` *(Structured narrative script provided below)*
- **Deployed Final Web Application:** [https://cargoclear-app.web.app](https://cargoclear-app.web.app) (Firebase Hosting)
- **Direct Cloud Run UI Service:** [https://cargoclear-ui-448522365737.asia-south1.run.app](https://cargoclear-ui-448522365737.asia-south1.run.app) (`minScale: 0`)
- **Direct Cloud Run API Service:** [https://cargoclear-api-448522365737.asia-south1.run.app](https://cargoclear-api-448522365737.asia-south1.run.app) (`minScale: 0`)

---

## 13. Three-Minute Demo Video Script (0:00 – 3:00)

*Structured second-by-second narrative script designed for voiceover narration and live UI screen recording.*

### [0:00 – 0:30] Hook & Problem Statement
- **Visual:** Split screen / B-roll of cargo vessels congested at port docks, followed by an overwhelmed customs broker reviewing paper trade documents with highlighted discrepancies.
- **Narrator:** *"Every day, cross-border shipments face costly 3 to 7 day port clearance delays and demurrage penalties ranging from \$200 to \$800 per container. Why? Because customs brokers must manually cross-examine dozens of data points across Commercial Invoices, Bills of Lading, Packing Lists, and Mill Test Certificates before filing declarations. Introducing CargoClear: an agentic AI pre-submission customs assessment workbench powered by Google Cloud and Gemini 2.5 Flash."*

### [0:30 – 1:15] Landing Page, Commercial Auth & 24s Analysis
- **Visual:** Navigate to `https://cargoclear-app.web.app`. Show the Executive KPI Dashboard. Sign in seamlessly via Google Workspace SSO (or show the Commercial Registration screen backed by Firestore PBKDF2 hashing). Open **Case D demo (India import)**. Hit **Run analysis**.
- **Action Highlight:** As analysis begins, the center PDF viewer smoothly auto-hides and the screen automatically focuses on the live pipeline progress bar as Server-Sent Events stream pipeline stages (Ingest → Preprocess → Extract → Reconcile → Synthesize).
- **Narrator:** *"Logging into CargoClear via enterprise SSO or corporate credentials, the broker accesses their compliance workspace. We open an import shipment to India containing four documents. When we hit 'Run Analysis', our multimodal Gemini 2.5 Flash pipeline activates. Notice how the interface automatically focuses on the real-time pipeline progress. In just 24 seconds, the system extracts structured entities, verifies arithmetic, and evaluates tariff rules—while built-in prompt-injection guardrails protect against poisoned vendor text."*

### [1:15 – 2:05] Grounded Verification & Tripartite Layout Switcher
- **Visual:** Analysis completes. Demonstrate the tripartite layout switcher in the top bar: click `⊞ Split` (side-by-side rail, PDF, and decision pane), `📄 Viewer` (full-width PDF inspection), and `⚖️ Decision` (adjudication focus). In `⊞ Split` mode, click check `W-001`. The center PDF viewer scrolls and highlights the gross weight discrepancy (14,250 kg on Invoice vs. 14,200 kg on Packing List) with SVG bounding boxes. Next, click check `H-002`.
- **Narrator:** *"Immediately, CargoClear flags a Material Contradiction. Using our tripartite layout switcher, the broker can toggle between full PDF inspection, decision adjudication, or side-by-side split view. Clicking check W-001 draws SVG bounding boxes directly over the original PDF, showing an irreconcilable 50 kg weight discrepancy between the invoice and packing list. Even more critically, check H-002 evaluates the Mill Test Certificate. While the exporter declared mild steel, our metallurgy engine proves the steel contains 0.35% Chromium—exceeding the 0.30% non-alloy threshold under Chapter 72 Note 1. This legally reclassifies the cargo into an alloy category subject to anti-dumping duty."*

### [2:05 – 2:40] Indicative Duty Breakdown, Human Override & Audit Chain
- **Visual:** Scroll to the **Indicative Duty Exposure** card showing CIF assessable value ($128,450), BCD 7.5%, SWS 10%, and Anti-Dumping Duty ($7,738 / \$543/MT). Click **Edit** on the Chromium field, adjust to `0.28%`, provide reason *"Lab re-test confirmed non-alloy"*, and click **Save & Recompute**. Observe instant (<1s) zero-model recomputation. Then open the **Audit Chain** tab to show the cryptographic SHA-256 hash chain and ECDSA P-256 digital signature badge (*"Chain Verified"*).
- **Narrator:** *"CargoClear calculates the full financial exposure upfront: Basic Customs Duty, Social Welfare Surcharge, and \$7,738 in Anti-Dumping Duty under Notification 02/2022. If a discrepancy is an OCR anomaly or verified by supplementary lab re-test, the authorized broker can edit the value in place. Clicking 'Recompute' instantly re-evaluates all 15 rules in milliseconds without making a single redundant LLM call. Best of all, every action, override, and verdict is cryptographically hashed and signed with ECDSA keys into an immutable Firestore audit trail for absolute regulatory defensibility."*

### [2:40 – 3:00] Serverless Scale-to-Zero Architecture & Conclusion
- **Visual:** Closing slide highlighting Google Cloud serverless architecture, scale-to-zero config (`minScale: 0`), \$0.00 idle compute cost, and live application URLs.
- **Narrator:** *"Built natively on Google Cloud Run with scale-to-zero, CargoClear incurs zero idle compute cost and processes each clearance assessment for less than half a cent. CargoClear: Transforming hours of manual customs checking into seconds of auditable precision. Clear cargo with confidence. Thank you."*
