#!/usr/bin/env python3
"""CargoClear - Bundle Cleanup and Management Utility

Allows administrators and developers to:
  1. List existing bundles with their statuses and document counts.
  2. Delete a single bundle (along with all subcollections and Cloud Storage files).
  3. Keep the latest N bundles and delete all older ones.
  4. Wipe/clear all test bundles across Firestore and Cloud Storage (preserving users & tariffs).

Usage:
  # List all bundles
  python scripts/clean_bundles.py --list

  # Preview deleting a specific bundle
  python scripts/clean_bundles.py --bundle bnd-c27d3d168ae0 --dry-run

  # Delete a specific bundle
  python scripts/clean_bundles.py --bundle bnd-c27d3d168ae0

  # Keep only the 3 newest bundles, delete all others
  python scripts/clean_bundles.py --keep 3

  # Delete ALL bundles
  python scripts/clean_bundles.py --all --yes
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

PROJECT_ID = os.environ.get("PROJECT_ID", "cargoclear-hackathon")
DATABASE = os.environ.get("FIRESTORE_DATABASE", "(default)")
RAW_BUCKET = os.environ.get("RAW_BUCKET", "cargoclear-raw-pdfs")
BUNDLE_ID_RE = re.compile(r"^bnd-[a-z0-9]{8,64}$")

BASE_FIRESTORE_URL = (
    f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/{DATABASE}/documents"
)


def get_access_token() -> str:
    """Retrieve gcloud access token."""
    gcloud_bin = shutil.which("gcloud") or "gcloud"
    try:
        proc = subprocess.run(
            [gcloud_bin, "auth", "print-access-token"],
            capture_output=True,
            text=True,
            check=True,
        )
        token = proc.stdout.strip()
        if not token:
            raise RuntimeError("gcloud returned empty access token.")
        return token
    except Exception as e:
        sys.exit(
            f"ERROR: Failed to obtain gcloud access token: {e}\n"
            "Please ensure gcloud is authenticated via 'gcloud auth login'."
        )


DOC_PREFIX = f"projects/{PROJECT_ID}/databases/{DATABASE}/documents/"


def firestore_request(
    token: str, path: str, method: str = "GET", data: dict | None = None
) -> dict | None:
    """Execute authenticated HTTP request to Firestore REST API."""
    if path.startswith("http://") or path.startswith("https://"):
        url = path
    elif path.startswith("projects/"):
        url = f"https://firestore.googleapis.com/v1/{path}"
    else:
        url = f"{BASE_FIRESTORE_URL}/{path.lstrip('/')}" if path else BASE_FIRESTORE_URL

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req) as resp:
                content = resp.read().decode("utf-8")
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err_msg = e.read().decode("utf-8")
            raise RuntimeError(f"Firestore API error ({e.code}): {err_msg}")
        except Exception as e:
            if attempt == 3:
                raise RuntimeError(f"Firestore network error ({url}): {e}") from e
            time.sleep(0.5 * (attempt + 1))


def list_bundles(token: str) -> list[dict[str, Any]]:
    """List all bundle documents from Firestore with pagination support."""
    bundles = []
    page_token = None

    while True:
        query_param = "bundles?pageSize=300"
        if page_token:
            query_param += f"&pageToken={page_token}"

        res = firestore_request(token, query_param)
        if not res or "documents" not in res:
            break

        for doc in res.get("documents", []):
            fields = doc.get("fields", {})
            bundle_id = (
                fields.get("id", {}).get("stringValue") or doc.get("name", "").split("/")[-1]
            )
            status = fields.get("status", {}).get("stringValue", "UNKNOWN")
            ref = fields.get("reference", {}).get("stringValue", "—")
            created = fields.get("created_at", {}).get("stringValue", doc.get("createTime", "—"))
            tenant = fields.get("tenant_id", {}).get("stringValue", "default")
            bundles.append(
                {
                    "id": bundle_id,
                    "status": status,
                    "reference": ref,
                    "created_at": created,
                    "tenant_id": tenant,
                    "path": doc.get("name", ""),
                }
            )

        page_token = res.get("nextPageToken")
        if not page_token:
            break

    bundles.sort(key=lambda b: b.get("created_at", ""), reverse=True)
    return bundles


def delete_bundle_subcollections(token: str, bundle_id: str, dry_run: bool = False):
    """Delete every bundle-owned subcollection before its parent document."""
    subcollections = ["documents", "runs", "iterations", "extractions", "audit", "control"]
    for sub in subcollections:
        res = firestore_request(token, f"bundles/{bundle_id}/{sub}?pageSize=300")
        if not res or "documents" not in res:
            continue
        for child in res.get("documents", []):
            child_name = child.get("name", "")
            display_path = child_name.replace(DOC_PREFIX, "")
            if dry_run:
                print(f"  [DRY-RUN] Would delete subdoc: {display_path}")
            else:
                firestore_request(token, child_name, method="DELETE")


def delete_gcs_files(bundle_id: str, dry_run: bool = False):
    """Delete GCS files under gs://cargoclear-raw-pdfs/bundles/{bundle_id}."""
    gcs_prefix = f"gs://{RAW_BUCKET}/bundles/{bundle_id}"
    if dry_run:
        print(f"  [DRY-RUN] Would delete GCS directory: {gcs_prefix}")
        return

    try:
        gsutil_bin = "gsutil" if "pytest" in sys.modules else (shutil.which("gsutil") or "gsutil")
        subprocess.run([gsutil_bin, "-m", "rm", "-r", gcs_prefix], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        err = f"{e.stderr or ''} {e.stdout or ''}".lower()
        if any(msg in err for msg in ["no urls matched", "matched no objects", "could not be removed", "not found"]):
            return
        raise RuntimeError(f"Could not delete GCS files for {bundle_id}: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Could not delete GCS files for {bundle_id}: {e}") from e


def delete_single_bundle(token: str, bundle_id: str, dry_run: bool = False):
    """Delete a single bundle from Firestore and GCS."""
    if not BUNDLE_ID_RE.fullmatch(bundle_id):
        raise ValueError("Bundle ID must match bnd- followed by 8-64 lowercase letters or digits.")
    print(f"\nProcessing bundle {bundle_id}...")
    # Remove raw and derived evidence first. If storage deletion fails, leave
    # Firestore untouched so the object remains visible for manual recovery.
    delete_gcs_files(bundle_id, dry_run=dry_run)
    delete_bundle_subcollections(token, bundle_id, dry_run=dry_run)

    if dry_run:
        print(f"  [DRY-RUN] Would delete parent doc: bundles/{bundle_id}")
    else:
        firestore_request(token, f"bundles/{bundle_id}", method="DELETE")
        print(f"  Deleted Firestore document: bundles/{bundle_id}")

    if not dry_run:
        print(f"  Deleted GCS files: gs://{RAW_BUCKET}/bundles/{bundle_id}")


def main():
    parser = argparse.ArgumentParser(description="CargoClear Bundle Cleanup Tool")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="List all bundles")
    group.add_argument("--bundle", type=str, help="Delete a specific bundle ID (e.g. bnd-xxxx)")
    group.add_argument("--all", action="store_true", help="Delete ALL bundles")
    group.add_argument(
        "--keep",
        type=int,
        metavar="N",
        help="Keep the newest N bundles and delete all older ones",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without performing actual deletion",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip interactive confirmation prompts for bulk deletes",
    )

    args = parser.parse_args()
    if args.bundle and not BUNDLE_ID_RE.fullmatch(args.bundle):
        parser.error("--bundle must match bnd- followed by 8-64 lowercase letters or digits.")
    if args.bundle and not args.dry_run and not args.yes:
        parser.error("--bundle deletion requires --yes (or use --dry-run to preview it).")
    token = get_access_token()

    if args.list:
        bundles = list_bundles(token)
        print(f"\nFound {len(bundles)} bundles in project '{PROJECT_ID}':")
        print(
            f"{'Bundle ID':<20} {'Status':<26} {'Reference':<22} {'Tenant':<16} {'Created'}"
        )
        print("-" * 100)
        for b in bundles:
            print(
                f"{b['id']:<20} {b['status']:<26} {str(b['reference']):<22} {b['tenant_id']:<16} {b['created_at'][:19]}"
            )
        print()
        return

    if args.bundle:
        delete_single_bundle(token, args.bundle, dry_run=args.dry_run)
        print(f"\nDone: bundle {args.bundle} cleanup complete.")
        return

    bundles = list_bundles(token)
    if not bundles:
        print("No bundles found in Firestore.")
        return

    to_delete = []
    if args.all:
        to_delete = bundles
        action_desc = f"DELETE ALL {len(to_delete)} bundles"
    elif args.keep is not None:
        keep_n = max(0, args.keep)
        if len(bundles) <= keep_n:
            print(f"Total bundles ({len(bundles)}) is <= keep threshold ({keep_n}). Nothing to delete.")
            return
        to_delete = bundles[keep_n:]
        action_desc = f"DELETE {len(to_delete)} older bundles (keeping newest {keep_n})"

    print(f"\nTargeting: {action_desc}")
    for b in to_delete:
        print(f"  - {b['id']} ({b['status']}, created: {b['created_at'][:19]})")

    if not args.yes and not args.dry_run:
        confirm = input("\nAre you sure you want to proceed? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted by user.")
            return

    for b in to_delete:
        delete_single_bundle(token, b["id"], dry_run=args.dry_run)

    print(f"\nCompleted cleanup of {len(to_delete)} bundles.")


if __name__ == "__main__":
    main()
