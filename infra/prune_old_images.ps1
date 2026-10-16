<#
.SYNOPSIS
    Prunes superseded/older container images in Artifact Registry, retaining
    only the active images currently referenced by Cloud Run service revisions.

.DESCRIPTION
    CargoClear Artifact Registry Pruning Script for Windows PowerShell.
    Queries Cloud Run to discover currently running container image digests,
    then inspects Artifact Registry and removes any superseded digests.

.EXAMPLE
    .\infra\prune_old_images.ps1 -Service cargoclear-ui
    .\infra\prune_old_images.ps1 -Service cargoclear-api
    .\infra\prune_old_images.ps1 -Service all
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Service = "all",

    [Parameter(Position = 1)]
    [string]$Package = "",

    [string]$ProjectId = $env:PROJECT_ID,
    [string]$Region = $env:REGION,
    [string]$Repo = "cloud-run-source-deploy",
    [switch]$DryRun
)

$ErrorActionPreference = "SilentlyContinue"
if (Test-Path Variable:\PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

if (-not $ProjectId) {
    $ProjectId = (gcloud config get-value project 2>$null)
    if (-not $ProjectId) {
        $ProjectId = "cargoclear-hackathon"
    }
}

if (-not $Region) {
    $Region = "asia-south1"
}

function Prune-ServiceImages {
    param(
        [string]$ServiceName,
        [string]$PackageName
    )

    if (-not $PackageName) {
        $PackageName = $ServiceName
    }

    $packagePath = "${Region}-docker.pkg.dev/${ProjectId}/${Repo}/${PackageName}"

    Write-Host "==================================================================" -ForegroundColor Cyan
    Write-Host "Pruning older images for service: $ServiceName (package: $PackageName)" -ForegroundColor Cyan
    Write-Host "Registry path: $packagePath" -ForegroundColor Cyan
    Write-Host "==================================================================" -ForegroundColor Cyan

    $activeDigests = [System.Collections.Generic.HashSet[string]]::new()

    # 1. Fetch template image from Cloud Run service
    try {
        $templateImg = (gcloud run services describe $ServiceName --region $Region --project $ProjectId --format="value(spec.template.spec.containers[0].image)" 2>$null)
        if ($templateImg -and $templateImg.Contains("@")) {
            $digest = $templateImg.Split("@")[-1].Trim()
            if ($digest) { [void]$activeDigests.Add($digest) }
        }
    } catch {
        Write-Warning "Could not retrieve template image for service ${ServiceName}: $_"
    }

    # 2. Fetch images from traffic-bearing revisions
    try {
        $trafficRevs = (gcloud run services describe $ServiceName --region $Region --project $ProjectId --format="value(status.traffic[].revisionName)" 2>$null)
        if ($trafficRevs) {
            foreach ($rev in ($trafficRevs -split "`r?`n")) {
                $rev = $rev.Trim()
                if (-not $rev) { continue }
                $revImg = (gcloud run revisions describe $rev --region $Region --project $ProjectId --format="value(status.containerStatuses[0].imageDigest,spec.containers[0].image)" 2>$null)
                if ($revImg) {
                    foreach ($item in ($revImg -split "\s+")) {
                        $item = $item.Trim()
                        if ($item.Contains("@")) {
                            [void]$activeDigests.Add($item.Split("@")[-1].Trim())
                        } elseif ($item.StartsWith("sha256:")) {
                            [void]$activeDigests.Add($item)
                        }
                    }
                }
            }
        }
    } catch {
        Write-Warning "Could not retrieve traffic revisions for service ${ServiceName}: $_"
    }

    if ($activeDigests.Count -eq 0) {
        Write-Warning "Could not identify any active image for service '$ServiceName' on Cloud Run."
        Write-Warning "Failing safe: skipping image deletion to prevent accidental data loss."
        return
    }

    Write-Host "Identified active image digest(s) currently running on Cloud Run:" -ForegroundColor Green
    foreach ($d in $activeDigests) {
        Write-Host "  -> $d" -ForegroundColor Green
    }

    # 3. List all images in Artifact Registry package
    $allVersionsRaw = (gcloud artifacts docker images list $packagePath --format="json" 2>$null)
    if (-not $allVersionsRaw) {
        Write-Host "No images found in $packagePath." -ForegroundColor Yellow
        return
    }

    try {
        $allVersionsObj = $allVersionsRaw | ConvertFrom-Json
    } catch {
        $allVersionsObj = @()
    }

    $keptCount = 0
    $prunedCount = 0

    foreach ($img in $allVersionsObj) {
        $version = $img.version
        if (-not $version) { continue }

        if ($activeDigests.Contains($version)) {
            Write-Host "  [KEEP] Active image in Cloud Run: $packagePath@$version" -ForegroundColor Green
            $keptCount++
        } else {
            if ($DryRun) {
                Write-Host "  [DRY-RUN] Would delete older image: $packagePath@$version" -ForegroundColor Yellow
            } else {
                Write-Host "  [DELETE] Deleting older image: $packagePath@$version ..." -ForegroundColor Red
                gcloud artifacts docker images delete "$packagePath@$version" --delete-tags --quiet
            }
            $prunedCount++
        }
    }

    Write-Host "Summary for $ServiceName`: kept $keptCount active image(s), pruned $prunedCount older image(s)." -ForegroundColor Cyan
}

if ($Service -eq "all") {
    Prune-ServiceImages -ServiceName "cargoclear-api" -PackageName "cargoclear-api"
    Prune-ServiceImages -ServiceName "cargoclear-ui" -PackageName "cargoclear-ui"
} elseif ($Package) {
    Prune-ServiceImages -ServiceName $Service -PackageName $Package
} else {
    Prune-ServiceImages -ServiceName $Service -PackageName $Service
}

Write-Host "Artifact Registry pruning finished successfully." -ForegroundColor Green
