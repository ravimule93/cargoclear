#!/usr/bin/env bash
# Record the product walkthrough as a video, a still per step and a manifest. The fallback for a demo that cannot run live.
#
#   scripts/record_demo.sh                         # demo mode on this machine (starts the backend and a production build of the UI)
#   scripts/record_demo.sh --live https://<ui>.run.app   # the deployed, live-mode stack (nothing is started)
#   options: --label NAME   a name for the folder (default demo-mode or live-mode)
#            --dwell MS     how long each caption stays on screen (default 2400)
#            --no-video     stills and manifest only (the video needs Playwright's ffmpeg: `npx playwright install ffmpeg`)
#
# Output: demo-recordings/<label>-<UTC time>/ with walkthrough.webm, screens/NN-*.png, steps.json and manifest.json.
# demo-recordings/ is git-ignored (binary, large): keep the recording where the team keeps files, not in the repository.
#
# A recording of the DEMO stack shows synthetic, file-name-keyed extraction: its captions say so, and the manifest records the mode.
# It is a recording of the interaction and the checks, not of the model reading a document. Only a --live recording shows that,
# and it can be made only against a deployed stack (docs/GCP_VERIFICATION.md). Read docs/DEMO_SCRIPT.md for what to say over it.
#
# Needs: Node 22 with `npm ci --legacy-peer-deps` done in frontend/ and `npx playwright install chromium`; for demo mode also backend/.venv.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND="${FRONTEND_DIR:-$ROOT/frontend}"   # FRONTEND_DIR: a checkout that has node_modules, when the repository's own does not
LIVE_URL=""
LABEL=""
DWELL="2400"
VIDEO_ON="yes"

while [ $# -gt 0 ]; do
  case "$1" in
    --live)  LIVE_URL="${2:?--live needs the UI address, for example https://cargoclear-ui-abc.a.run.app}"; shift 2 ;;
    --label) LABEL="${2:?--label needs a name}"; shift 2 ;;
    --dwell) DWELL="${2:?--dwell needs milliseconds}"; shift 2 ;;
    --no-video) VIDEO_ON="no"; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done

if [ ! -d "$FRONTEND/node_modules" ]; then
  echo "ERROR: $FRONTEND/node_modules is missing. Run: cd frontend && npm ci --legacy-peer-deps && npx playwright install chromium" >&2
  exit 1
fi
if [ -z "$LIVE_URL" ] && [ ! -x "$ROOT/backend/.venv/bin/uvicorn" ] && ! curl -fs http://localhost:8080/healthz >/dev/null 2>&1; then
  echo "ERROR: backend/.venv is missing and no backend answers on :8080 (demo mode starts one). See docs/HOW_TO_RUN_AND_DEMO.md, section 2." >&2
  exit 1
fi

MODE="demo-mode"; [ -n "$LIVE_URL" ] && MODE="live-mode"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$ROOT/demo-recordings/${LABEL:-$MODE}-$STAMP"
mkdir -p "$OUT"

export DEMO_OUT_DIR="$OUT" DEMO_DWELL_MS="$DWELL"
[ "$VIDEO_ON" = "no" ] && export DEMO_VIDEO=off
[ -n "$LIVE_URL" ] && export DEMO_BASE_URL="$LIVE_URL"

echo "Recording the ${MODE} walkthrough into $OUT"
( cd "$FRONTEND" && export NODE_TLS_REJECT_UNAUTHORIZED=0 && npx playwright test -c playwright.demo.config.ts )

if [ "$VIDEO_ON" = "yes" ]; then
  VIDEO="$(find "$OUT/raw" -name '*.webm' | head -n 1)"
  if [ -z "$VIDEO" ]; then
    echo "ERROR: Playwright produced no video under $OUT/raw (is ffmpeg installed? npx playwright install ffmpeg)" >&2
    exit 1
  fi
  cp "$VIDEO" "$OUT/walkthrough.webm"
fi
rm -rf "$OUT/raw"

COMMIT="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
DIRTY="no"; [ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ] && DIRTY="yes"

OUT="$OUT" COMMIT="$COMMIT" DIRTY="$DIRTY" python3 - <<'PY'
import hashlib, json, os, pathlib
out = pathlib.Path(os.environ["OUT"])
steps = json.loads((out / "steps.json").read_text())
video = out / "walkthrough.webm"
has_video = video.exists()
manifest = {
    "what": "Recorded walkthrough of the CargoClear workbench: Case C, Case D, a correction and recompute, the pre-fill, the signed audit trail.",
    "recorded_at": steps["recorded_at"],
    "app_mode": steps["app_mode"],
    "stack": steps["base_url_kind"],
    "source_commit": os.environ["COMMIT"],
    "uncommitted_changes_when_recorded": os.environ["DIRTY"] == "yes",
    "video": (
        {"file": "walkthrough.webm", "bytes": video.stat().st_size, "sha256": hashlib.sha256(video.read_bytes()).hexdigest()}
        if has_video else None
    ),
    "length_seconds": steps["steps"][-1]["at_seconds"] if steps["steps"] else None,
    "honesty": (
        "DEMO MODE: extraction is synthetic and keyed on file names; no model was called. This shows the workflow and the deterministic checks, not document reading."
        if steps["app_mode"] == "demo"
        else "LIVE MODE: the stack read the PDFs with the configured Gemini model. The documents are synthetic samples, not scans."
    ),
    "steps": [{"n": s["n"], "at_seconds": s["at_seconds"], "title": s["title"], "caption": s["caption"], "screenshot": s["screenshot"]} for s in steps["steps"]],
}
(out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print((f"video: {video} ({video.stat().st_size // 1024} KiB), " if has_video else "no video (stills only), ") + f"{len(steps['steps'])} steps, mode {steps['app_mode']}")
PY
echo "Done: $OUT"
echo "Mode: ${MODE}. Say so when you show it."
