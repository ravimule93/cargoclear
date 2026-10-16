#!/usr/bin/env python3
"""What the preprocessing stage costs the SERVER for a fixture: wall time and peak memory of ``preprocess.run`` (no Gemini, no network).

    cd backend
    .venv/bin/python -I tests/gating/probe_render.py NAME [NAME ...] [--rss-limit-mb 3000]

``NAME`` is a file in tests/fixtures/gating (a path under it, e.g. ``f01_clean/commercial_invoice.pdf``). Each file is rendered in a
CHILD process that a watchdog kills the moment its resident memory crosses the limit, so a decompression-bomb fixture cannot take the
machine down. The answer per file: ``killed`` (the limit was crossed: the render would have needed more than that), or the pages
produced, the MIME of what would be sent to the model, its size, the seconds and the peak resident memory.

A JSON line per file is printed (prefix ``PROBE``) for the audit to quote. Synthetic fixtures only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parents[1]
FIXTURES = HERE.parent / "fixtures" / "gating"


def child(name: str) -> int:
    sys.path.insert(0, str(BACKEND_DIR))
    from app.services import preprocess

    raw = (FIXTURES / name).read_bytes()
    started = time.perf_counter()
    result = asyncio.run(preprocess.run({"raw_bytes": raw, "document_id": "probe"}))
    pages = result["processed_pages"]
    print("CHILD " + json.dumps({
        "pages": len(pages), "mime": sorted({p["mime"] for p in pages}), "payload_bytes": sum(len(p["payload"]) for p in pages),
        "seconds": round(time.perf_counter() - started, 2),
    }))
    return 0


def rss_mb(pid: int) -> float:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return int(out) / 1024 if out else 0.0


def probe(name: str, limit_mb: float) -> dict:
    process = subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), "--child", name], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True)
    peak, started, killed = 0.0, time.perf_counter(), False
    while process.poll() is None:
        # poppler runs as a grandchild: count the children of the Python process as well
        children = subprocess.run(["pgrep", "-P", str(process.pid)], capture_output=True, text=True).stdout.split()
        total = rss_mb(process.pid) + sum(rss_mb(int(pid)) for pid in children)
        peak = max(peak, total)
        if total > limit_mb:
            killed = True
            for pid in children:
                subprocess.run(["kill", "-9", pid], capture_output=True)
            process.kill()
            break
        time.sleep(0.1)
    process.wait()
    out = process.stdout.read() if process.stdout else ""
    child_result = next((json.loads(line[6:]) for line in out.splitlines() if line.startswith("CHILD ")), None)
    return {"file": name, "killed_at_limit": killed, "limit_mb": limit_mb, "peak_rss_mb": round(peak),
            "wall_seconds": round(time.perf_counter() - started, 2), **(child_result or {})}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*")
    parser.add_argument("--child", metavar="NAME")
    parser.add_argument("--rss-limit-mb", type=float, default=3000)
    args = parser.parse_args(argv)
    if args.child:
        return child(args.child)
    for name in args.names:
        print("PROBE " + json.dumps(probe(name, args.rss_limit_mb)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
