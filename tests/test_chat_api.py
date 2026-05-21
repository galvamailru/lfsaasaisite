"""Tests for chat API: POST message, SSE (mocked LLM)."""
import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models import Tenant


@pytest.mark.asyncio
async def test_chat_post_empty_message_400(async_client, db_session):
    """POST /api/v1/tenants/{id}/chat with empty message returns 400."""
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "test"))).scalar_one()
    r = await async_client.post(
        f"/api/v1/tenants/{tenant.id}/chat",
        json={"user_id": "u1", "message": "   "},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_chat_post_returns_sse_with_mocked_llm(async_client, db_session):
    """POST /api/v1/tenants/{id}/chat returns SSE stream when LLM is mocked."""
    tenant = (await db_session.execute(select(Tenant).where(Tenant.slug == "test"))).scalar_one()

    async def mock_stream(*args, **kwargs):
        yield "Hello "
        yield "world"

    with patch("app.routers.chat.stream_chat", new=mock_stream):
        with patch("app.routers.chat._get_prompt", return_value="You are a helper"):
            r = await async_client.post(
                f"/api/v1/tenants/{tenant.id}/chat",
                json={"user_id": "u1", "message": "Hi"},
            )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    text = r.text
    assert "Hello" in text
    assert "world" in text
