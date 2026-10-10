"""Tests for scripts/generate_case_c_pdfs.py and the committed fixtures/case_c/*.pdf."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytest.importorskip("reportlab")

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "generate_case_c_pdfs.py"
COMMITTED_DIR = REPO_ROOT / "fixtures" / "case_c"
FILENAMES = [
    "commercial_invoice.pdf",
    "bill_of_lading.pdf",
    "packing_list.pdf",
    "mtc_pipe_test_cert.pdf",
]


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_case_c_pdfs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_generates_four_pdfs(generator: ModuleType, tmp_path: Path) -> None:
    written = generator.generate(tmp_path)
    assert sorted(p.name for p in written) == sorted(FILENAMES)
    for path in written:
        assert path.read_bytes().startswith(b"%PDF")


def test_pdfs_have_distinct_bytes(generator: ModuleType, tmp_path: Path) -> None:
    generator.generate(tmp_path)
    digests = {sha256(tmp_path / name) for name in FILENAMES}
    assert len(digests) == len(FILENAMES)


def test_generation_is_deterministic(generator: ModuleType, tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    generator.generate(first)
    generator.generate(second)
    for name in FILENAMES:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_committed_pdfs_match_generator(generator: ModuleType, tmp_path: Path) -> None:
    """Drift guard: re-run `python scripts/generate_case_c_pdfs.py` if the fixtures change."""
    generator.generate(tmp_path)
    for name in FILENAMES:
        committed = COMMITTED_DIR / name
        assert committed.is_file(), f"{committed} missing; run scripts/generate_case_c_pdfs.py"
        assert committed.read_bytes() == (tmp_path / name).read_bytes(), (
            f"{name} is stale; re-run scripts/generate_case_c_pdfs.py"
        )


def test_printed_values_come_from_fixtures(generator: ModuleType) -> None:
    """Spot-check the single source of truth: the invoice prints the corrected arithmetic."""
    content = generator.render_pdf("commercial_invoice.pdf")
    for expected in (b"700.0", b"84000.0", b"120 LENGTHS", b"INV-2024-001"):
        assert expected in content
    assert b"84500" not in content and b"LENTHS" not in content


def test_weights_are_printed_with_their_unit(generator: ModuleType) -> None:
    """Each weight prints as "<value> <unit>" ("14000.0 KGS") so the sample documents actually state their units."""
    expected = {
        "packing_list.pdf": [b"(14000.0 KGS)", b"(14280.0 KGS)", b"(280.0 KGS)"],
        "bill_of_lading.pdf": [b"(14280.0 KGS)"],
        "commercial_invoice.pdf": [b"(14000.0 KGS)", b"(14280.0 KGS)"],
        "mtc_pipe_test_cert.pdf": [b"(14000.0 KGS)", b"(14280.0 KGS)"],
    }
    for filename, strings in expected.items():
        content = generator.render_pdf(filename)
        for text in strings:
            assert text in content, f"{filename}: {text!r} not printed"


def test_non_weight_values_print_without_a_unit(generator: ModuleType) -> None:
    content = generator.render_pdf("commercial_invoice.pdf")
    for text in (b"(700.0)", b"(84000.0)", b"(120 LENGTHS)", b"(USD)", b"(73041900)"):
        assert text in content, f"{text!r} should print exactly as before"
