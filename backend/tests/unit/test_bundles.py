"""Unit tests for bundle endpoints and Firestore repository integration."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_create_bundle_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/bundles",
            json={"reference": "REF-SG-001", "destination_country": "SG"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"].startswith("bnd-")
        assert data["reference"] == "REF-SG-001"
        assert data["destination_country"] == "SG"
        assert data["status"] == "PENDING"
        assert data["current_iteration"] == 0


@pytest.mark.asyncio
async def test_get_bundle_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create first
        create_resp = await client.post(
            "/api/v1/bundles",
            json={"reference": "REF-SG-002", "destination_country": "SG"},
        )
        bundle_id = create_resp.json()["id"]

        # Fetch
        get_resp = await client.get(f"/api/v1/bundles/{bundle_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["id"] == bundle_id
        assert data["reference"] == "REF-SG-002"


@pytest.mark.asyncio
async def test_get_bundle_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/bundles/nonexistent-bundle-id")
        assert resp.status_code == 404
        data = resp.json()
        assert data["code"] == "NOT_FOUND"
        assert "not found" in data["message"].lower()
