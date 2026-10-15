# Minutes of Meeting (MoM)
## Google Cloud AI Builder Cup 2026 | Ask the Expert Session

---

### **Executive Summary & Meeting Metadata**

| Attribute | Details |
| :--- | :--- |
| **Event Name** | Google Cloud AI Builder Cup 2026 — Ask the Expert Session |
| **Theme / Track** | *"Build in JAPAC, Build for the World"* |
| **Date & Time** | 15 October 2026 \| 2:00 PM IST (14:00 – 14:53 IST) |
| **Duration** | 53 Minutes 26 Seconds |
| **Host / Platform** | Hack2skill (H2S) — Hosted by **Manit Ahuja** |
| **Featured Speaker** | **Abirami Sukumaran** (Staff Developer Advocate, Google Cloud) |
| **Official Support** | `support+aibuildercup@hack2skill.com` |
| **Target Participants** | Working professionals, startup builders, and enterprise engineers across JAPAC |
| **Submission Deadline** | **18 October 2026** (Hard Deadline on Hack2skill dashboard) |
| **Grand Finale Date** | **4 December 2026** |

---

### **1. Key Hackathon Timelines & Milestones**

```
   15 Oct 2026                  18 Oct 2026                  Late Oct - Nov 2026            04 Dec 2026
┌────────────────┐           ┌────────────────┐           ┌─────────────────────┐        ┌────────────────┐
│ Ask the Expert │ ────────> │   Submissions  │ ────────> │   Jury Evaluation   │ ─────> │  Grand Finale  │
│  Live Session  │           │  Close (Hard)  │           │   (Keep App Live)   │        │   & Showcase   │
└────────────────┘           └────────────────┘           └─────────────────────┘        └────────────────┘
```

1. **Submissions Close:** **18 October 2026** (No deadline extension announced; teams must submit all five components before midnight).
2. **Evaluation Window:** Begins immediately post-18 October. The deployed prototype **must remain accessible and functional** throughout this window.
3. **Repository Freeze:** Evaluators examine code based on the commit state at the submission deadline. Subsequent commits must be limited to zero-feature bug fixes.
4. **Grand Finale:** **4 December 2026** for shortlisted finalists.

---

### **2. Mandatory Submission Deliverables ("Five Things Go In")**

Every team must submit exactly five components via the Hack2skill participant dashboard:

```
                                  MANDATORY SUBMISSION (5 DELIVERABLES)
  ┌───────────────────────┬──────────────────────┬──────────────────────┬──────────────────────┬──────────────────────┐
  │     1. Pitch Deck     │    2. Demo Video     │   3. Deployed App    │    4. GitHub Repo    │   5. Project Brief   │
  ├───────────────────────┼──────────────────────┼──────────────────────┼──────────────────────┼──────────────────────┤
  │ • Official template   │ • 3 to 4 minutes max │ • Public URL         │ • Public / Accessible│ • Technical summary  │
  │ • Max 15–16 slides    │ • End-to-end working │ • Active through     │ • Clean README       │ • Google AI stack    │
  │ • Architecture + ROI  │ • First 30s hook     │   judging cycle      │ • Architecture docs  │   breakdown          │
  └───────────────────────┴──────────────────────┴──────────────────────┴──────────────────────┴──────────────────────┘
```

1. **Pitch Deck (Official Prescribed Template):**
   - Must use the official slide deck template provided on the dashboard (maximum 15–16 slides).
   - Core slides: Problem statement, market opportunity in JAPAC, technical architecture diagram, Google Cloud/AI services breakdown, business viability & ROI, team credentials, and demo test login credentials.
2. **Demo Video (3–4 Minutes Walkthrough):**
   - Duration: Strict 3–4 minutes (dashboard states "up to 3 minutes"; aim for a punchy 3:00–3:30 mins).
   - Must demonstrate a **live, functioning application** solving the stated problem end-to-end.
   - Video editing is permitted (e.g., trimming out LLM response latency or database spin-up), but functionality must be authentic.
   - **Crucial Rule:** The first 30 seconds must immediately show the problem and the working application in action. Do not spend 60 seconds on static team slides.
3. **Live Deployed Prototype URL:**
   - Deployed on a publicly accessible endpoint (e.g., Cloud Run URL or Firebase Hosting domain).
   - If authentication is required (Google Sign-In / OAuth / basic credentials), **test credentials and step-by-step access instructions must be clearly provided in both the README and Pitch Deck**.
4. **Accessible GitHub Repository:**
   - Complete source code with clear project structure.
   - Public repository preferred; if private, explicit read access must be granted to the judging panel.
   - Must include an exhaustive `README.md` containing: architectural diagrams, local run instructions, environment variables template (`.env.example`), and explanation of AI agent logic.
5. **Brief Written Solution Description:**
   - Concise executive summary detailing the problem addressed, target enterprise users, and the Google Cloud AI architecture deployed.

---

### **3. The Two Disqualification Rules ("Two Conditions Decide Whether It Qualifies")**

> [!CAUTION]
> Failure to satisfy either of these two conditions leads to immediate disqualification:
> 1. **Built with Google AI Technologies:** The core intelligent capabilities must be powered by Google Cloud GenAI (Gemini 2.5/1.5, Gemma, Vertex AI, Agent Development Kit, or Vertex AI Agent Builder).
> 2. **Prototype Availability Throughout Evaluation:** The deployed application **must not crash or throw 500/404 errors** when judges test it. If the link is down during judging, the entry is disqualified.

---

### **4. Judging Criteria & Weightage Breakdown**

The judging rubric allocates 100 total points across four structured pillars:

```
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                         JUDGING CRITERIA (100%)                             │
  ├──────────────────────────────────────────────────────┬──────────────────────┤
  │ Criteria Pillar                                      │ Weightage            │
  ├──────────────────────────────────────────────────────┼──────────────────────┤
  │ 1. Technical Merit & Google AI Implementation        │ 40%                  │
  │ 2. Problem Alignment & Real-World Impact (JAPAC)     │ 25%                  │
  │ 3. Innovation & Architectural Creativity             │ 25%                  │
  │ 4. User Experience, Solution Design & Presentation   │ 10%                  │
  └──────────────────────────────────────────────────────┴──────────────────────┘
```

#### Detailed Scoring Expectations:
- **Technical Merit (40%):**
  - Sophistication of Gemini / Vertex AI agentic workflows (multi-step planning, function calling, structured JSON output).
  - Proper separation of concerns: **Deterministic tools perform math, validations, and database checks; LLM performs cognitive reasoning and explanation**.
  - Grounding evidence: Showing clear verification traces that prevent hallucinations.
  - Production-readiness of Google Cloud infrastructure (Cloud Run, Secret Manager, Cloud SQL/Firestore).
- **Problem Alignment & Impact (25%):**
  - Real-world enterprise/industry relevance tailored to JAPAC (supply chain, customs, finance, logistics, healthcare).
  - Measurable efficiency gains, cost reductions, or risk mitigation.
- **Innovation & Creativity (25%):**
  - Moving beyond trivial prompt wrappers or standard conversational chatbots.
  - Autonomous multi-agent coordination, proactive alerts, multimodal inspection (document OCR + tabular + satellite/visual).
- **UX & Presentation (10%):**
  - Clean UI/UX flow, clear error feedback, professional pitch deck, crisp 3-minute video delivery.

---

### **5. Technical Deep Dive: Key Architectural Guidelines**

#### A. Models & Agent Development
- **SDK & Framework Choice:**
  - Teams are **free to choose** between **Vertex AI Agent Builder**, **Python ADK (Agent Development Kit 2.0)**, or the **`@google/genai` SDK** hosted on Cloud Run with function calling.
  - Judges evaluate the **deployed outcome, orchestration quality, and reasoning accuracy**, not the specific UI builder vs code framework.
- **Hybrid Architecture (Fine-Tuned Models + Gemini):**
  - Combining specialized local/open models (e.g., YOLO for object detection, LayoutLM for document bounding boxes, or XGBoost for tabular fraud scoring) with **Gemini for high-level reasoning and decision-making** is strongly encouraged and scores exceptionally well under Technical Merit.
- **Grounding & Hallucination Prevention:**
  - Internal grounding via deterministic function calling (querying custom databases, APIs, and business rule engines) is completely valid.
  - Evaluators want to see explicit grounding evidence: log outputs, source citations, and deterministic boundary checks in the code.
- **Agent Latency & Tool Execution:**
  - For multi-step workflows executing 3–5 tool calls, run independent tool invocations in parallel.
  - Leverage **Gemini 2.5 Flash** for high-velocity agentic reasoning loops.

#### B. Deploying on Google Cloud
- **Cloud Run Cold Start Prevention:**
  - Set **Startup CPU Boost** in Cloud Run to accelerate initialization.
  - For containers loading local weights or heavy dependencies, configure `min-instances: 1` during the judging window post-18 October to eliminate 20–40 second cold-start delays.
  - Ensure Cloud Run timeout is configured appropriately (e.g., 300s–600s) to prevent ADK timeouts on complex reasoning runs.
- **Region Strategy:**
  - `us-central1` offers maximum Vertex AI feature availability, highest quota limits, and new model variants.
  - `asia-southeast1` (Singapore) provides the lowest network latency for JAPAC users.
  - Architecture recommendation: Cloud Run frontend/backend in `asia-southeast1` or `us-central1`, connecting to Vertex AI in `us-central1`.
- **Infrastructure Architecture:**
  - Decoupling frontend (Firebase Hosting / Cloud Run), backend API (Cloud Run), and database (Cloud SQL / Firestore / Supabase) is fully supported and recommended.
  - **Secrets Management:** Storing API keys or service account credentials in code repositories is strictly penalized. Use **Google Cloud Secret Manager** or Cloud Run environment variables.

#### C. Data & Integrations: Synthetic vs Real Data
- **Synthetic & Simulated Data:**
  - **100% acceptable** for industrial, maritime, customs, or enterprise scenarios where proprietary or real-time live APIs (e.g., live AIS vessel radar, customs clearinghouse feeds, confidential invoices) are inaccessible.
  - **Requirement:** Clearly label simulated feeds in the UI, README, and Pitch Deck (e.g., *"Simulated AIS Radar Feed via synthetic generator"*).

---

### **6. Top Q&A Catalog (Audience Inquiries & Expert Guidance)**

| # | Question Raised | Expert Guidance / Clarification |
| :- | :--- | :--- |
| **1** | *Can we use Python ADK 2.0 in code on Cloud Run instead of Agent Builder?* | **Yes, absolutely.** You are free to develop agents programmatically using Python ADK or GenAI SDK and deploy to Cloud Run. Judges evaluate the functional intelligence, tool orchestration, and stability. |
| **2** | *Is synthetic or simulated data acceptable for demo/evaluation?* | **Yes.** Synthetic data, backtested data, or simulated feeds (e.g. AIS vessel telemetry, customs invoices) are completely valid as long as they are transparently documented and labeled. |
| **3** | *What is the required video duration (deck says 3–4 mins, form says 3 mins)?* | Aim for **3:00 to 3:30 minutes maximum**. Keep it concise, rapid, and demo-first. Do not exceed 4 minutes under any circumstances. |
| **4** | *Can the demo URL require login/authentication?* | **Yes.** Google Sign-In or basic authentication is acceptable, provided test credentials and frictionless access instructions are clearly given in the pitch deck and README. |
| **5** | *Our container is large and cold start takes 30s. How should we configure Cloud Run?* | Enable **Startup CPU Boost** and set `min-instances: 1` during the active evaluation window immediately following October 18 to avoid judge timeouts. |
| **6** | *Does our backend and database need to run in the same service?* | **No.** Decoupled microservices (e.g. Cloud Run API + managed database + Firebase frontend) represent best practice. |
| **7** | *Can we combine custom fine-tuned models with Gemini (hybrid architecture)?* | **Yes, strongly encouraged.** Using specialized computer vision or classification models alongside Gemini for reasoning and synthesis demonstrates technical depth. |
| **8** | *Will Google provide custom cloud credits or vouchers for the hackathon?* | No individual custom vouchers were issued during the session; participants must utilize standard GCP free-tier allocations or trial credits. |
| **9** | *Can we submit a private GitHub repository?* | Public repos are strongly preferred. If private, you must ensure read permissions are granted to the judging accounts specified on the dashboard. |
| **10** | *Can we continue committing to the GitHub repository after 18 October?* | Submissions are evaluated based on the **commit state at the 18 October deadline**. Critical bug fixes can be committed, but judges will inspect timestamps for new features. |
| **11** | *What should the first 30 seconds of the video demonstrate?* | Hook the judge immediately: state the real-world enterprise problem in 10 seconds, then immediately showcase the live product executing a workflow. Avoid prolonged slide intros. |
| **12** | *How to handle Gemini 503 / quota limit errors during evaluation?* | Implement automatic client-side exponential backoff retries, multi-region fallback, or graceful degradation so the evaluator never encounters an unhandled exception. |
| **13** | *Are desktop or native mobile applications (APK / iOS) eligible?* | Web applications are strongly preferred for seamless browser evaluation. If submitting an APK/desktop app, provide a direct download link, test credentials, and an exhaustive video recording. |
| **14** | *Are part-time graduate students who are working professionals eligible?* | Working professionals and startup founders are eligible. Full-time students without employment are ineligible. Inquiries should be sent to `support+aibuildercup@hack2skill.com`. |
| **15** | *Can we use an existing solution built in the past?* | Pre-existing platforms can be leveraged, but evaluation focuses strictly on the newly developed Google Cloud GenAI capabilities and features built for this competition. |

---

### **7. Direct Action Plan for CargoClear-JAPAC**

Based on the expert session requirements, here is the immediate checklist to ensure CargoClear-JAPAC scores in the top tier:

```
  ┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                           CARGOCLEAR-JAPAC SUBMISSION READINESS CHECKLIST                       │
  ├──────┬─────────────────────────┬─────────────────────────────────────────────────┬──────────────┤
  │ Area │ Requirement             │ CargoClear Implementation Action                │ Status       │
  ├──────┼─────────────────────────┼─────────────────────────────────────────────────┼──────────────┤
  │ 1    │ Pitch Deck (Max 16 pgs) │ Port content into prescribed Hack2skill deck    │ In Progress  │
  │ 2    │ Demo Video (3 mins)     │ Record 3-min script: 30s Hook -> Live Extraction│ Ready        │
  │ 3    │ Cloud Run Config        │ Set min-instances: 1 + Startup CPU Boost        │ Configured   │
  │ 4    │ Deterministic Tooling   │ Tool calling for HS code & 100% tax math checks │ Implemented  │
  │ 5    │ Synthetic Data Notice   │ Explicitly label Donut invoice & AIS vessel mock│ Documented   │
  │ 6    │ Secrets Management      │ Verify Vertex AI & Gemini keys in Secret Manager│ Verified     │
  │ 7    │ GitHub README           │ Add architecture diagram + test login guide     │ Updated      │
  └──────┴─────────────────────────┴─────────────────────────────────────────────────┴──────────────┘
```

---
*MoM prepared and synchronized directly within the primary CargoClear workspace.*
