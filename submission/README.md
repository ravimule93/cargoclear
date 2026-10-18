# CargoClear — AI Builder Cup Submission Package

Welcome to the **CargoClear-JAPAC** submission package for the **Google Cloud AI Builder Cup 2026**.

> **Team Name:** CargoClear  
> **Team Leader:** Ravi Mule  
> **Team Member:** Nikhil Pande  
> **Live Web App:** [https://cargoclear-app.web.app](https://cargoclear-app.web.app)  
> **Backend API:** [https://cargoclear-api-448522365737.asia-south1.run.app](https://cargoclear-api-448522365737.asia-south1.run.app)  
> **GitHub Repository:** [https://github.com/ravimule93/cargoclear](https://github.com/ravimule93/cargoclear)  

---

## 📦 Package Contents

1. **`CargoClear_AI_Builder_Cup_Submission.pptx`**  
   The fully populated presentation deck built strictly using the authoritative **`Submission Template _ AI Builder Cup.pptx`**. Contains all 16 template slides with factual, production-verified details, architecture diagrams, zero-idle cost model, and performance benchmarks.

2. **`SUBMISSION_DOSSIER.md`**  
   A complete, exhaustive markdown document following the 16 slides of the official rubric. Includes:
   - Team details and problem statement
   - In-depth product narrative and opportunities
   - Detailed feature inventory with 5-label status taxonomy
   - Mermaid process flow and architecture diagrams
   - Wireframes and 3-pane workbench specification
   - Verified performance benchmarks (24.3s Case D end-to-end execution)
   - 3-Minute Demo Video narrative script (0:00–3:00)

3. **`generate_deck.py`**  
   The automation script used to generate the `.pptx` deck directly from the master PowerPoint template.

---

## 🌐 Production Deployments & Live Links

- **Main Production Web Application:** [https://cargoclear-app.web.app](https://cargoclear-app.web.app) (Firebase Hosting)
- **Direct Cloud Run UI Service:** [https://cargoclear-ui-448522365737.asia-south1.run.app](https://cargoclear-ui-448522365737.asia-south1.run.app) (`minScale: 0`)
- **Direct Cloud Run API Service:** [https://cargoclear-api-448522365737.asia-south1.run.app](https://cargoclear-api-448522365737.asia-south1.run.app) (`minScale: 0`)
- **GitHub Public Repository:** [https://github.com/ravimule93/cargoclear](https://github.com/ravimule93/cargoclear) (branch: `improvement-plan`)

> [!IMPORTANT]
> **3-Minute Demo Video Recording:**
> - **Video Link:** `[DEMO VIDEO LINK — Insert YouTube / Google Drive / Loom URL here]`
> - **Narrative Talk Track:** Fully scripted second-by-second in [`SUBMISSION_DOSSIER.md` Section 13](SUBMISSION_DOSSIER.md#13-three-minute-demo-video-script-000--300) (0:00–3:00) covering Case D, Gemini 2.5 Flash extraction, metallurgy verification, indicative anti-dumping duty calculation, and cryptographic SHA-256 / ECDSA audit ledger.

---

## ⚡ Quick Test & Verification Commands

To verify the live deployed environment end-to-end:

```bash
# 1. Test live Case D import assessment with Gemini 2.5 Flash and Anti-Dumping validation:
python scripts/test_case_d_live.py

# 2. Test prompt-injection guardrails against adversarial vendor documents:
python scripts/live_injection_test.py

# 3. Regenerate the submission PowerPoint presentation:
python submission/generate_deck.py
```

---

## 🏆 Key Submission Highlights

- **Speed:** Full 4-document trade bundle processed, reconciled, and audited in **24.3 seconds**.
- **Accuracy:** **100% discrepancy detection** on weights, Incoterms, currency, and chemical composition without LLM hallucination.
- **Defensibility:** Dual-layer **SHA-256 hash chaining + ECDSA P-256 digital signatures** in an immutable Firestore audit ledger.
- **Zero Idle Compute Cost:** Both API and UI run on Google Cloud Run with **`--min-instances 0` (scale-to-zero)**, resulting in **$0.00 idle compute cost**.
- **Low Operating Cost:** Less than **$0.006 per customs clearance assessment** running serverless on Google Cloud Platform (~$11.40 – $29.40 / mo for 5,000 monthly assessments).
- **Tripartite Clearance Workbench:** Next.js 15 workbench with layout switcher (`⊞ Split`, `📄 Viewer`, `⚖️ Decision`), auto-hiding PDF view during analysis with automated focus scrolling to the live progress bar.
- **Enterprise Multi-Tenancy:** Google Workspace SSO plus commercial user registration/sign-in backed by Cloud Firestore with PBKDF2-HMAC-SHA256 salted password hashing.

