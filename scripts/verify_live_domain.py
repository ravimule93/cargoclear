#!/usr/bin/env python3
"""Read-only live-mode smoke check for the public UI and private API."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def get_json(url: str, headers: dict[str, str] | None = None) -> dict:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail when a purported live CargoClear deployment exposes demo mode.")
    parser.add_argument("--ui-url", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--identity-token", required=True)
    args = parser.parse_args()
    try:
        meta = get_json(f"{args.ui_url.rstrip('/')}/api/proxy/meta")
        version = get_json(
            f"{args.api_url.rstrip('/')}/version",
            {"Authorization": f"Bearer {args.identity_token}"},
        )
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as error:
        print(f"LIVE MODE VERIFICATION FAILED: {error}", file=sys.stderr)
        return 1
    modes = {"/api/proxy/meta": meta.get("app_mode"), "/version": version.get("app_mode")}
    if any(mode != "live" for mode in modes.values()) or meta.get("user") is not None:
        print(f"LIVE MODE VERIFICATION FAILED: unexpected public state: {modes}, user={meta.get('user')!r}", file=sys.stderr)
        return 1
    print("LIVE MODE VERIFIED: UI metadata and private API version report live with no public user session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
