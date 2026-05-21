"""Tests for cabinet API: by-slug, dialogs, saved, profile."""
import pytest
from sqlalchemy import select

from app.models import Tenant


@pytest.mark.asyncio
async def test_tenant_by_slug_ok(async_client, db_session):
    """GET /api/v1/tenants/by-slug/{slug} returns tenant when exists."""
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "test"))).scalar_one()
    r = await async_client.get("/api/v1/tenants/by-slug/test")
    assert r.status_code == 200
    data = r.json()
    assert data["slug"] == "test"
    assert data["name"] == "Test Tenant"
    assert "id" in data


@pytest.mark.asyncio
async def test_tenant_by_slug_404(async_client):
    """GET /api/v1/tenants/by-slug/nonexistent returns 404."""
    r = await async_client.get("/api/v1/tenants/by-slug/nonexistent")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_me_dialogs_requires_user_id(async_client, db_session):
    """GET /api/v1/tenants/{id}/me/dialogs without X-User-Id returns 400."""
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "test"))).scalar_one()
    r = await async_client.get(f"/api/v1/tenants/{tenant.id}/me/dialogs")
    assert r.status_code == 422  # FastAPI returns 422 for missing header dependency


@pytest.mark.asyncio
async def test_me_dialogs_ok(async_client, db_session):
    """GET /api/v1/tenants/{id}/me/dialogs with X-User-Id returns list."""
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "test"))).scalar_one()
    r = await async_client.get(f"/api/v1/tenants/{tenant.id}/me/dialogs", headers={"X-User-Id": "user1"})
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_me_profile_ok(async_client, db_session):
    """GET /api/v1/tenants/{id}/me/profile returns profile or defaults."""
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "test"))).scalar_one()
    r = await async_client.get(f"/api/v1/tenants/{tenant.id}/me/profile", headers={"X-User-Id": "user1"})
    assert r.status_code == 200
    data = r.json()
    assert data["user_id"] == "user1"
