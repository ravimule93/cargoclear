# CargoClear-JAPAC

> Pre-submission adversarial customs adjudicator for JAPAC cross-border trade.
> Built for Google Cloud AI Builder Cup 2026.

---

## Architecture Overview

CargoClear is structured as a two-tier decoupled system:
- **Frontend (`frontend/`)**: Next.js 15 (App Router, React 19, TypeScript, Tailwind CSS v4). Implements the investigator-style 4-panel workbench, interactive bounding-box overlays, and WCAG 2.2 AA accessibility live regions.
- **Backend (`backend/`)**: FastAPI (Python 3.12, Pydantic v2). Orchestrates multimodal extraction (Gemini 2.5 Flash), deterministic mathematical verification, BigQuery Vector Search grounding (AHTN), and hash-chained Firestore audit trails.
- **Infrastructure (`infra/`)**: GCP bootstrap scripts, BigQuery Vector Index DDL (TreeAH), and Cloud Build pipeline.

---

## Directory Structure

```
cargoclear/
├── frontend/             # Next.js 15 App Router UI & BFF proxy
├── backend/              # FastAPI application, services, and agent wrappers
├── infra/                # GCP deployment, BigQuery DDL, and bootstrap scripts
├── cloudbuild.yaml       # Multi-service build and deployment pipeline
└── .gitignore
```

---

## Getting Started

### Prerequisites
- Node.js ≥ 18
- Python ≥ 3.10
- Google Cloud SDK (`gcloud`)

### 1. Backend Setup
```bash
cd backend
python3 -m venv venv
# Linux / macOS
source venv/bin/activate
# Windows PowerShell
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run unit tests (deterministic calculations)
pytest
```

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

Visit [http://localhost:3000](http://localhost:3000) to open the adjudication workbench.
