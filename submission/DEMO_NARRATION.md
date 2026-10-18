# CargoClear-JAPAC — Demo Narration Script

> **Google Cloud AI Builder Cup 2026** | Track: *"Build in JAPAC, Build for the World"*  
> **Total Video Duration**: **00:02:55.96** | **Voice Model**: Microsoft Azure Neural TTS (`en-US-ChristopherNeural`)  
> **Synchronization Standard**: Frame-accurate alignment with Playwright browser events (`steps.json`). Zero audio collisions.

---

## Frame-Synchronized Narration Timeline

### [0:01 – 0:13] Scene 1: Workbench Overview & Human-in-the-Loop Philosophy
- **Browser Action**: Landing on `https://cargoclear-app.web.app` (`at_seconds: 5.1s`). Broker selects destination Singapore (`SG`) and creates a new bundle.
- **Voiceover (`seg01_intro`)**:
  > *"Welcome to CargoClear, an agentic pre-submission customs compliance workbench powered by Google Cloud Vertex AI and Gemini 2.5 Flash, providing verified decision support for licensed brokers."*

---

### [0:14 – 0:29] Scene 2: Case C Upload & Multimodal Extraction
- **Browser Action**: Case C documents uploaded (Commercial Invoice, Bill of Lading, Packing List) (`at_seconds: 13.9s`). Agent clicks "Run analysis". Multimodal pipeline reading starts.
- **Voiceover (`seg02_case_c_upload`)**:
  > *"In Case C, an export from India to Singapore, three trade documents are uploaded: an invoice, bill of lading, and packing list. We run analysis to extract fields and evaluate cross-border customs rules in real time."*

---

### [0:39 – 0:52] Scene 3: Case C Missing Evidence & Certificate Addition
- **Browser Action**: Status pill updates to `Missing Evidence` (`at_seconds: 39.7s`). Agent uploads missing Mill Test Certificate and initiates reassessment.
- **Voiceover (`seg03_case_c_missing`)**:
  > *"CargoClear immediately flags missing evidence: the declared HS code mandates a certified Mill Test Certificate. When the agent supplies the certificate, the bundle re-evaluates automatically."*

---

### [0:69 – 0:82] Scene 4: Case C Compliant, Reasoning Delta & Audit Trail
- **Browser Action**: Status turns green `Compliant For Submission` (`at_seconds: 69.2s`). Agent inspects Reasoning Delta (`72.6s`) and clicks Audit Trail (`76.4s`, `Chain verified`).
- **Voiceover (`seg04_case_c_compliant`)**:
  > *"With the certificate verified, status transitions to Compliant for Submission. The Reasoning Delta transparently details what changed, and the SHA-256 audit ledger confirms procedural integrity."*

---

### [0:87 – 1:01] Scene 5: Case D Import Bundle Ingestion
- **Browser Action**: Agent opens Case D India Import (`at_seconds: 86.5s`), loading four documents. Clicks "Run analysis".
- **Voiceover (`seg05_case_d_upload`)**:
  > *"Now let's examine Case D, an industrial steel pipe shipment imported into India declared under non-alloy HS 7304.19. All four trade documents are submitted for multimodal analysis."*

---

### [1:26 – 1:36] Scene 6: Case D Material Contradiction & Duty Notice
- **Browser Action**: Status turns red `Material Contradiction` (`at_seconds: 126.3s`). Viewer scrolls to MTC chemistry table, highlighting Heat TH-77121 with Chromium 0.35%.
- **Voiceover (`seg06_case_d_contradiction`)**:
  > *"Contradiction detected: heat TH-77121 reports 0.35% chromium, classifying this as alloy steel under Note 1."*

---

### [1:37 – 1:47] Scene 7: Broker Correction & Audit Trail
- **Browser Action**: Agent clicks "Correct Certificate cell" (`at_seconds: 135.0s`), inputs `0.28%`, enters justification, and clicks Save (`139.6s`, `Pending recompute`).
- **Voiceover (`seg07_correction`)**:
  > *"The broker inspects the certificate, corrects chromium to 0.28%, and logs the reason. The correction remains pending until recomputed."*

---

### [1:47 – 1:55] Scene 8: Zero-Token Recompute & Specialist Review
- **Browser Action**: Agent clicks "Recompute checks" (`at_seconds: 146.8s`). Status transitions to `Specialist Review Required` without model re-calling. Delta inspected (`150.5s`).
- **Voiceover (`seg08_recompute`)**:
  > *"Recompute instantly executes the deterministic rules with zero LLM tokens, updating status to Specialist Review Required."*

---

### [1:56 – 2:13] Scene 9: Customs Pre-Fill Pack, Cryptographic Signing & Closing
- **Browser Action**: Agent views Customs Pre-Fill Pack JSON/PDF (`at_seconds: 154.0s`) and verifies Cloud KMS signed audit ledger (`157.8s`).
- **Voiceover (`seg09_prefill_audit_close`)**:
  > *"Finally, the Customs Pre-Fill Pack exports grounded page citations, while the audit chain is digitally signed by Google Cloud KMS. Built on Cloud Run with scale-to-zero efficiency, CargoClear delivers fast, verifiable compliance for cross-border trade."*

---

## Technical Metadata & Audio Quality

- **Master Video File**: [`submission/CargoClear_AI_Builder_Cup_Demo.mp4`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/cargoclear/submission/CargoClear_AI_Builder_Cup_Demo.mp4)
- **Audio Master**: [`submission/voiceover_synced.wav`](file:///C:/Users/703292978/OneDrive%20-%20Genpact/Documents/workspaces/workspace_antigravity/cargoclear/submission/voiceover_synced.wav)
- **Voice Engine**: Microsoft Azure Neural Speech (`en-US-ChristopherNeural`)
- **Sample Rate**: 44,100 Hz, 16-bit PCM uncompressed master $\to$ AAC 192 kbps export
- **Video Resolution**: 1440×900 progressive, 25 fps, H.264 High Profile
- **Total Duration**: 00:02:55.96 (175.96 seconds)
- **File Size**: 6.9 MB
