<#
.SYNOPSIS
    Automated GCP Deployment Script for CargoClear-JAPAC (Windows PowerShell).

.DESCRIPTION
    Deploys CargoClear backend (cargoclear-api) and frontend (cargoclear-ui) to Google Cloud Run
    with scale-to-zero (0 idle instances), least-privilege service accounts, Secret Manager mounting,
    and automatic Artifact Registry container image pruning.

.PARAMETER ProjectId
    The Google Cloud Project ID. Defaults to current active gcloud project or $env:PROJECT_ID.

.PARAMETER Region
    The GCP region for Cloud Run and Vertex AI. Defaults to 'asia-south1' (Mumbai).

.PARAMETER MinInstances
    Minimum container instances. Defaults to 0 (Scale to Zero for maximum cost savings).

.PARAMETER UseCloudBuild
    Switch to run the entire deployment remotely via Cloud Build (cloudbuild.yaml) instead of local CLI.

.EXAMPLE
    .\infra\deploy.ps1
    .\infra\deploy.ps1 -ProjectId "cargoclear-hackathon" -MinInstances 0
    .\infra\deploy.ps1 -UseCloudBuild
#>

param(
    [string]$ProjectId = $env:PROJECT_ID,
    [string]$Region = $(if ($env:REGION) { $env:REGION } else { "asia-south1" }),
    [int]$MinInstances = 0,
    [switch]$UseCloudBuild = $false,
    [switch]$SkipBootstrap = $false
)

$ErrorActionPreference = "Stop"

# 1. Validate gcloud is installed
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Error "Google Cloud SDK (gcloud) is not found in PATH. Please install gcloud CLI."
    exit 1
}

# 2. Resolve Project ID
if ([string]::IsNullOrWhiteSpace($ProjectId)) {
    $ProjectId = (gcloud config get-value project 2>$null).Trim()
}
if ([string]::IsNullOrWhiteSpace($ProjectId) -or $ProjectId -eq "(unset)") {
    Write-Error "Project ID not set. Specify -ProjectId or run 'gcloud config set project <PROJECT_ID>'."
    exit 1
}

$env:PROJECT_ID = $ProjectId
$env:REGION = $Region

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "🚀 CargoClear-JAPAC Automated Deployment" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Project ID     : $ProjectId" -ForegroundColor Yellow
Write-Host "Target Region  : $Region" -ForegroundColor Yellow
Write-Host "Min Instances  : $MinInstances $(if ($MinInstances -eq 0) { '(Scale to Zero: $0 Idle Cost)' })" -ForegroundColor Green
Write-Host "Mode           : $(if ($UseCloudBuild) { 'Cloud Build (Remote)' } else { 'Direct Cloud Run (Local CLI)' })" -ForegroundColor Yellow
Write-Host "============================================================`n"

$RuntimeSa = "cargoclear-sa@$($ProjectId).iam.gserviceaccount.com"
$UiSa = "cargoclear-ui-sa@$($ProjectId).iam.gserviceaccount.com"

# 3. Ensure Bootstrap (APIs, SAs, GCS, Firestore, BigQuery)
if (-not $SkipBootstrap) {
    Write-Host "[1/6] Verifying and bootstrapping GCP environment..." -ForegroundColor Cyan
    
    # Check if SA exists; if not, run bootstrap
    $saCheck = gcloud iam service-accounts describe $RuntimeSa --project $ProjectId 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Service account $RuntimeSa not found. Running Day-0 bootstrap..." -ForegroundColor Yellow
        gcloud services enable run.googleapis.com aiplatform.googleapis.com firestore.googleapis.com storage.googleapis.com bigquery.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com --project $ProjectId
        
        # Create SAs
        gcloud iam service-accounts create cargoclear-sa --display-name="CargoClear API Runtime SA" --project $ProjectId 2>$null
        gcloud iam service-accounts create cargoclear-ui-sa --display-name="CargoClear UI Service SA" --project $ProjectId 2>$null
        
        # IAM Bindings for Runtime SA
        foreach ($role in @("roles/aiplatform.user", "roles/storage.objectAdmin", "roles/bigquery.dataViewer", "roles/bigquery.jobUser", "roles/datastore.user", "roles/secretmanager.secretAccessor")) {
            gcloud projects add-iam-policy-binding $ProjectId --member="serviceAccount:$RuntimeSa" --role="$role" --quiet 2>$null
        }
        # IAM Bindings for UI SA
        gcloud projects add-iam-policy-binding $ProjectId --member="serviceAccount:$UiSa" --role="roles/secretmanager.secretAccessor" --quiet 2>$null

        # Foundational storage
        gsutil mb -p $ProjectId -l $Region "gs://cargoclear-raw-pdfs" 2>$null
        gcloud firestore databases create --project $ProjectId --region $Region 2>$null
        bq --location=$Region mk -d --project_id=$ProjectId "ahtn" 2>$null
    } else {
        Write-Host "Service accounts and base infrastructure already provisioned." -ForegroundColor Green
    }
}

# 4. Ensure Secrets exist in Secret Manager
Write-Host "`n[2/6] Verifying Secret Manager secrets..." -ForegroundColor Cyan
$jwtSecret = gcloud secrets describe auth-jwt-secret --project $ProjectId 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Generating automated secure auth-jwt-secret in Secret Manager..." -ForegroundColor Yellow
    $randKey = [System.Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    $randKey | gcloud secrets create auth-jwt-secret --data-file=- --project $ProjectId --replication-policy="automatic"
}

$clientSecret = gcloud secrets describe google-client-secret --project $ProjectId 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating placeholder google-client-secret (update via Google Cloud Console if using custom OAuth)..." -ForegroundColor Yellow
    "placeholder-secret-replace-in-console" | gcloud secrets create google-client-secret --data-file=- --project $ProjectId --replication-policy="automatic"
}

# 5. Remote Cloud Build Execution
if ($UseCloudBuild) {
    Write-Host "`n[3/6] Submitting build to Google Cloud Build..." -ForegroundColor Cyan
    $sha = (git rev-parse --verify HEAD 2>$null)
    if (-not $sha) { $sha = "prod-latest" }
    $ts = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")

    gcloud builds submit --config=cloudbuild.yaml `
        --project $ProjectId `
        --substitutions=_REGION="$Region",_RUNTIME_SERVICE_ACCOUNT="$RuntimeSa",_UI_SERVICE_ACCOUNT="$UiSa",_MIN_INSTANCES="$MinInstances",_RELEASE_SHA="$sha",_RELEASE_TIMESTAMP="$ts"
    
    Write-Host "`n✅ Cloud Build deployment completed successfully!" -ForegroundColor Green
    exit 0
}

# 6. Direct Deployment Mode
$ThrottleFlag = if ($MinInstances -eq 0) { "--cpu-throttling" } else { "--no-cpu-throttling" }

Write-Host "`n[3/6] Building and deploying cargoclear-api (Private Cloud Run, MinInstances: $MinInstances)..." -ForegroundColor Cyan
gcloud run deploy cargoclear-api `
    --source ./backend `
    --project $ProjectId `
    --region $Region `
    --timeout 1200 `
    --memory 4Gi `
    --cpu 2 `
    --concurrency 80 `
    --min-instances $MinInstances `
    --max-instances 1 `
    $ThrottleFlag `
    --service-account $RuntimeSa `
    --no-allow-unauthenticated `
    --quiet `
    --set-secrets="AUTH_JWT_SECRET=auth-jwt-secret:latest" `
    --set-env-vars `
APP_MODE="live",`
AUTH_ENABLED="true",`
ENABLE_API_DOCS="false",`
PROJECT_ID="$ProjectId",`
REGION="$Region",`
RAW_BUCKET="cargoclear-raw-pdfs",`
FIRESTORE_DATABASE="(default)",`
BQ_DATASET="ahtn",`
BQ_MODEL_EMBEDDING="embedding_model",`
GEMINI_LIVE_MODEL="gemini-2.5-flash",`
GEMINI_LIVE_LOCATION="$Region",`
GEMINI_MAX_OUTPUT_TOKENS="16384",`
DAILY_TOKEN_BUDGET="5000000",`
RUN_TIMEOUT_SECONDS="1200",`
CLIENT_IP_HEADER="x-cargoclear-client-ip",`
TRUST_FORWARDED_FOR="false"

$ApiUrl = (gcloud run services describe cargoclear-api --region $Region --project $ProjectId --format="value(status.url)").Trim()
Write-Host "cargoclear-api deployed at: $ApiUrl (Private)" -ForegroundColor Green

Write-Host "`n[4/6] Binding UI service account permission on private API..." -ForegroundColor Cyan
gcloud run services add-iam-policy-binding cargoclear-api `
    --region $Region `
    --project $ProjectId `
    --member "serviceAccount:$UiSa" `
    --role "roles/run.invoker" `
    --quiet >$null

Write-Host "`n[5/6] Building and deploying cargoclear-ui (Public Cloud Run, MinInstances: 0)..." -ForegroundColor Cyan
gcloud run deploy cargoclear-ui `
    --source ./frontend `
    --project $ProjectId `
    --region $Region `
    --port 8080 `
    --timeout 300 `
    --concurrency 80 `
    --min-instances 0 `
    --service-account $UiSa `
    --allow-unauthenticated `
    --quiet `
    --set-secrets="GOOGLE_CLIENT_SECRET=google-client-secret:latest" `
    --set-env-vars `
API_BASE="$ApiUrl",`
API_AUTH_MODE="google-id-token",`
TRUSTED_PROXY_HOPS="1",`
NEXT_PUBLIC_APP_MODE="live"

$UiUrl = (gcloud run services describe cargoclear-ui --region $Region --project $ProjectId --format="value(status.url)").Trim()
Write-Host "cargoclear-ui deployed at: $UiUrl (Public)" -ForegroundColor Green

# 7. Automatically Prune Old Container Images
Write-Host "`n[6/6] Pruning older Artifact Registry container images..." -ForegroundColor Cyan
.\infra\prune_old_images.ps1 -Service cargoclear-api -ErrorAction SilentlyContinue
.\infra\prune_old_images.ps1 -Service cargoclear-ui -ErrorAction SilentlyContinue

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host "🎉 DEPLOYMENT COMPLETED SUCCESSFULLY!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "🌐 Public UI URL      : $UiUrl" -ForegroundColor Cyan
Write-Host "🔒 Private API URL   : $ApiUrl" -ForegroundColor Cyan
Write-Host "⚡ Scaling Policy    : Scale-to-Zero active (0 idle instances = $0 idle cost)" -ForegroundColor Green
Write-Host "============================================================`n"
