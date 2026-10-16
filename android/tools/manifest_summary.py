#!/usr/bin/env python3
"""What the BUILT app asks for and exports: the permissions and the exported components of the merged manifest.

    cd android && ./gradlew :app:processHostedReleaseManifest
    python3 tools/manifest_summary.py            # prints the summary of the hosted release build
    python3 tools/manifest_summary.py --write    # rewrites fixtures/hosted_release_manifest.json (after a library was added or updated)

The app's own AndroidManifest.xml is only part of what ships: Gradle merges in what each library declares (WorkManager brings two permissions,
a job service and two receivers, for one). The record in fixtures/hosted_release_manifest.json is that merged result, checked by
backend/tests/unit/test_android_contract.py: a new permission or exported component can only come in by someone running this with --write
and updating the list in that test. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ANDROID_DIR = Path(__file__).resolve().parents[1]
MERGED = ANDROID_DIR / "app" / "build" / "intermediates" / "merged_manifests" / "hostedRelease" / "processHostedReleaseManifest" / "AndroidManifest.xml"
RECORD = ANDROID_DIR / "fixtures" / "hosted_release_manifest.json"
ANDROID = "{http://schemas.android.com/apk/res/android}"


def summarise(manifest_text: str) -> dict:
    """The sorted permissions asked for, and every component that is exported (with the permission a caller must hold, or null)."""
    root = ET.fromstring(manifest_text)
    permissions = sorted(node.get(f"{ANDROID}name") for node in root.findall("uses-permission"))
    exported = []
    application = root.find("application")
    for kind in ("activity", "activity-alias", "service", "receiver", "provider"):
        for node in application.findall(kind):
            if node.get(f"{ANDROID}exported") == "true":
                exported.append({"kind": kind, "name": node.get(f"{ANDROID}name"), "permission": node.get(f"{ANDROID}permission")})
    exported.sort(key=lambda c: (c["kind"], c["name"]))
    return {"build": "hostedRelease", "permissions": permissions, "exported": exported}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help=f"rewrite {RECORD.relative_to(ANDROID_DIR)}")
    args = parser.parse_args()
    if not MERGED.exists():
        print(f"{MERGED.relative_to(ANDROID_DIR)} does not exist: run ./gradlew :app:processHostedReleaseManifest first", file=sys.stderr)
        return 1
    text = json.dumps(summarise(MERGED.read_text(encoding="utf-8")), indent=2) + "\n"
    if args.write:
        RECORD.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
