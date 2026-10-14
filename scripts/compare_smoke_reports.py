#!/usr/bin/env python3
"""Compare two live_smoke_extraction.py reports: which expectations passed in one and failed in the other.

    python3 scripts/compare_smoke_reports.py REPORT_A.json REPORT_B.json

For the A/B of the model's input (--page-mode bw against gray, --deskew against none) on the same files. Prints, per
document, every expectation that differs, then totals; the exit code is 0 either way (it informs a decision, it makes none).
No network, no credentials; reads the two JSON files only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def failed_by_document(report: dict[str, Any]) -> dict[str, set[str]]:
    """{file: names of the expectations that failed in ANY run}."""
    out: dict[str, set[str]] = {}
    for doc in report.get("documents", []):
        failed: set[str] = set()
        for run in doc.get("runs", []):
            failed.update(((run.get("check") or {}).get("failed")) or [])
            if "error" in run:
                failed.add("(extraction failed)")
        out[doc["file"]] = failed
    return out


def describe(report: dict[str, Any]) -> str:
    env = report.get("environment", {})
    return f"page_image_mode={env.get('page_image_mode', '?')} deskew={env.get('preprocess_deskew', '?')} model={env.get('model', '?')}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two smoke-test reports.")
    parser.add_argument("a", type=Path)
    parser.add_argument("b", type=Path)
    args = parser.parse_args(argv)
    a, b = (json.loads(path.read_text()) for path in (args.a, args.b))
    fa, fb = failed_by_document(a), failed_by_document(b)

    print(f"A: {args.a.name}  {describe(a)}\nB: {args.b.name}  {describe(b)}\n")
    only_a_total = only_b_total = 0
    for file in sorted(set(fa) | set(fb)):
        if file not in fa or file not in fb:
            print(f"{file}: only in {'A' if file in fa else 'B'}")
            continue
        worse_in_b, worse_in_a = sorted(fb[file] - fa[file]), sorted(fa[file] - fb[file])
        only_a_total, only_b_total = only_a_total + len(worse_in_a), only_b_total + len(worse_in_b)
        if worse_in_a or worse_in_b:
            print(file)
            for name in worse_in_b:
                print(f"  fails only in B: {name}")
            for name in worse_in_a:
                print(f"  fails only in A: {name}")
    print(f"\nfailures only in A: {only_a_total}   failures only in B: {only_b_total}   "
          f"(totals: A {sum(len(v) for v in fa.values())}, B {sum(len(v) for v in fb.values())})")
    print("A and B are the same on every expectation." if not only_a_total and not only_b_total else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
