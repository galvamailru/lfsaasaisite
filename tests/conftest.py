"""Pytest fixtures: app, client, db session, mocks."""
import asyncio
from collections.abc import AsyncGenerator, Generator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import get_db
from app.main import app
from app.models import Base, Tenant

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def engine():
    eng = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autocommit=False, autoflush=False
    )
    async with async_session() as session:
        tenant = Tenant(id=uuid4(), slug="test", name="Test Tenant")
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)
        yield session


@pytest.fixture
def override_get_db(db_session):
    async def _get_db():
        yield db_session
    return _get_db


@pytest.fixture
def client(override_get_db) -> TestClient:
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def async_client(override_get_db):
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
