"""C6: CreateBundleRequest cleans and bounds what it accepts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.config import settings
from app.domain.schemas import CreateBundleRequest
from tests.helpers import api_client


@pytest.mark.asyncio
async def test_a_reference_is_stripped_and_cleaned_of_control_characters() -> None:
    async with api_client() as client:
        response = await client.post("/api/v1/bundles", json={"reference": "  SHP-1\r\n\t\x00 / 2  ", "destination_country": "sg"})

    assert response.status_code == 201
    assert response.json()["reference"] == "SHP-1 / 2" or response.json()["reference"] == "SHP-1 / 2".replace(" ", " ")
    assert response.json()["destination_country"] == "SG"


def test_stripping_and_control_removal_happen_in_the_model() -> None:
    assert CreateBundleRequest(reference="  abc  ").reference == "abc"
    assert CreateBundleRequest(reference="a\x00b\x1fc\x7fd\x85e").reference == "abcde"
    assert CreateBundleRequest(reference="line1\nline2").reference == "line1line2"
    assert CreateBundleRequest(reference="  \x00 abc \x00  ").reference == "abc"
    assert CreateBundleRequest(reference="发票-1").reference == "发票-1"
    assert CreateBundleRequest().reference is None
    assert CreateBundleRequest(reference=None).reference is None


def test_a_reference_at_the_limit_is_accepted_and_one_over_is_refused() -> None:
    assert settings.max_reference_chars == 200
    assert len(CreateBundleRequest(reference="r" * 200).reference) == 200

    with pytest.raises(PydanticValidationError) as raised:
        CreateBundleRequest(reference="r" * 201)

    assert "at most 200 characters" in str(raised.value)


def test_the_limit_is_measured_after_cleaning_and_never_truncates(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_reference_chars", 5)

    assert CreateBundleRequest(reference="  abcde  ").reference == "abcde"  # 9 raw characters, 5 after stripping
    with pytest.raises(PydanticValidationError):
        CreateBundleRequest(reference="abcdef")


@pytest.mark.asyncio
async def test_a_too_long_reference_is_a_422_and_creates_nothing(monkeypatch) -> None:
    async with api_client() as client:
        response = await client.post("/api/v1/bundles", json={"reference": "r" * 201})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR" and ["body", "reference"] in [e["loc"] for e in body["detail"]["errors"]]
    assert "r" * 50 not in response.text, "the input is not echoed"
    from app.repo import firestore

    assert firestore._IN_MEMORY_BUNDLES == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("country", ["ZZZZZZZZ", "S", "", "S1", "1G", "S G", "SGP", "é", "SG\n"])
async def test_a_destination_country_must_be_two_letters(country) -> None:
    async with api_client() as client:
        response = await client.post("/api/v1/bundles", json={"destination_country": country})

    assert response.status_code == 422, response.text
    assert ["body", "destination_country"] in [e["loc"] for e in response.json()["detail"]["errors"]]


@pytest.mark.asyncio
@pytest.mark.parametrize(("sent", "stored"), [("sg", "SG"), ("Id", "ID"), ("IN", "IN")])
async def test_a_two_letter_country_is_accepted_and_upper_cased(sent, stored) -> None:
    async with api_client() as client:
        response = await client.post("/api/v1/bundles", json={"destination_country": sent})

    assert response.status_code == 201 and response.json()["destination_country"] == stored


@pytest.mark.asyncio
async def test_the_default_country_is_still_sg() -> None:
    async with api_client() as client:
        response = await client.post("/api/v1/bundles", json={})

    assert response.status_code == 201 and response.json()["destination_country"] == "SG"


@pytest.mark.asyncio
async def test_the_bundle_created_audit_payload_stays_small() -> None:
    async with api_client() as client:
        created = await client.post("/api/v1/bundles", json={"reference": "r" * 200, "destination_country": "sg"})
        audit = (await client.get(f"/api/v1/bundles/{created.json()['id']}/audit")).json()

    [event] = [e for e in audit["events"] if e["event_type"] == "BUNDLE_CREATED"]
    assert event["payload"] == {
        "reference": "r" * 200,
        "destination_country": "SG",
        "tenant_id": "customs.com",
        "created_by": "demo-cha@customs.com",
    }
    import json

    assert len(json.dumps(event["payload"])) < 400


@pytest.mark.asyncio
async def test_a_two_megabyte_reference_cannot_reach_the_audit_log() -> None:
    async with api_client() as client:
        big = await client.post("/api/v1/bundles", json={"reference": "r" * 2_000_000})

    assert big.status_code == 413
    from app.services import audit

    assert audit._IN_MEMORY_AUDIT == {}
