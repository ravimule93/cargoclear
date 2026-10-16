#!/usr/bin/env python3
"""Writes the open-source licence list the About screen shows, from what the release build really ships.

    cd android && python3 tools/list_licenses.py            # rewrites app/src/main/res/raw/licenses.txt
    cd android && python3 tools/list_licenses.py --check    # fails if that file is not what the build would produce now

It asks Gradle for the resolved runtime classpath of the hosted release build, reads each library's licence from its POM in the Gradle cache
(following `<parent>` where the licence is inherited), and groups the libraries by licence and by family (`androidx`, `com.squareup.okhttp3`, ...).
Nothing is written from memory: a library whose POM names no licence, or one that is not Apache 2.0, is printed and, for the second kind, kept
under its own heading, so a change in what is shipped shows up as a change of this file. Needs the dependencies to be in the Gradle cache
(run a build first). Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ANDROID_DIR = Path(__file__).resolve().parents[1]
OUT = ANDROID_DIR / "app" / "src" / "main" / "res" / "raw" / "licenses.txt"
CACHE = Path.home() / ".gradle" / "caches" / "modules-2" / "files-2.1"
POM_CACHE = Path.home() / ".cache" / "cargoclear-licences"
REPOSITORIES = ("https://dl.google.com/dl/android/maven2", "https://repo1.maven.org/maven2")
CONFIGURATION = "hostedReleaseRuntimeClasspath"
COORDINATE = re.compile(r"([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-+]+)(?: -> ([A-Za-z0-9_.\-+]+))?")
NS = {"m": "http://maven.apache.org/POM/4.0.0"}


def resolved_libraries() -> dict[tuple[str, str], str]:
    text = subprocess.run(
        ["./gradlew", ":app:dependencies", "--configuration", CONFIGURATION, "-q"], cwd=ANDROID_DIR, capture_output=True, text=True, check=True
    ).stdout
    found: dict[tuple[str, str], str] = {}
    for line in text.splitlines():
        if "project :" in line or not re.search(r"[+\\]--- ", line):
            continue
        match = COORDINATE.search(line.split("--- ", 1)[1])
        if match:
            group, artifact, declared, resolved = match.groups()
            found[(group, artifact)] = resolved or declared
    return found


def pom_of(group: str, artifact: str, version: str) -> Path | None:
    """The library's POM: from Gradle's cache when it kept one, else the published file from Google Maven or Maven Central (kept locally).
    Gradle reads Gradle Module Metadata for most libraries and never downloads their POMs, and that metadata carries no licence."""
    base = CACHE / group / artifact / version
    hits = sorted(base.glob(f"*/{artifact}-{version}.pom")) if base.exists() else []
    if hits:
        return hits[0]
    local = POM_CACHE / group / f"{artifact}-{version}.pom"
    if local.exists():
        return local
    for repository in REPOSITORIES:
        url = f"{repository}/{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}.pom"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)
        return local
    return None


def licence_names(group: str, artifact: str, version: str, depth: int = 0) -> list[str]:
    pom = pom_of(group, artifact, version)
    if pom is None or depth > 4:
        return []
    root = ET.parse(pom).getroot()
    names = [
        (n.text or "").strip()
        for n in root.findall("m:licenses/m:license/m:name", NS) + root.findall("licenses/license/name")
        if n.text and n.text.strip()
    ]
    if names:
        return names
    parent = root.find("m:parent", NS) if root.find("m:parent", NS) is not None else root.find("parent")
    if parent is not None:
        def field(tag: str) -> str:
            node = parent.find(f"m:{tag}", NS) if parent.find(f"m:{tag}", NS) is not None else parent.find(tag)
            return (node.text or "").strip() if node is not None else ""
        return licence_names(field("groupId"), field("artifactId"), field("version"), depth + 1)
    return []


def normalise(name: str) -> str:
    lowered = name.lower()
    if "apache" in lowered:
        return "Apache License 2.0"
    if "mit" in lowered.split() or lowered.startswith("the mit"):
        return "MIT License"
    if "bsd" in lowered:
        return "BSD licence"
    if "android software development kit" in lowered:
        return "Android Software Development Kit License"
    return name


def family(group: str) -> str:
    parts = group.split(".")
    if parts[0] == "androidx":
        return "androidx"
    return group


def render() -> tuple[str, list[str]]:
    libs = resolved_libraries()
    by_licence: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    problems: list[str] = []
    for (group, artifact), version in sorted(libs.items()):
        names = {normalise(n) for n in licence_names(group, artifact, version)}
        if not names:
            problems.append(f"no licence in the POM of {group}:{artifact}:{version}")
            names = {"Licence not stated in the library's POM"}
        for name in names:
            by_licence[name][family(group)].add(artifact)
    lines = [
        "Open-source components in this app, by licence.",
        "Generated from the libraries the release build ships (android/tools/list_licenses.py); each licence is the one the library's own POM names.",
        "",
    ]
    for name in sorted(by_licence, key=lambda n: (n != "Apache License 2.0", n)):
        groups = by_licence[name]
        total = sum(len(v) for v in groups.values())
        lines.append(f"{name} ({total} librar{'y' if total == 1 else 'ies'})")
        for fam in sorted(groups):
            lines.append(f"  {fam} ({len(groups[fam])})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n", problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the checked-in file is not what the build would produce")
    args = parser.parse_args()
    text, problems = render()
    for problem in problems:
        print("warning:", problem, file=sys.stderr)
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT.relative_to(ANDROID_DIR)} is out of date: run tools/list_licenses.py", file=sys.stderr)
            return 1
        print("licence list is current")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
