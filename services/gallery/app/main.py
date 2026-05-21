"""CIP Gallery microservice. Схема БД: gallery."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routers import router
from app.mcp_router import router as mcp_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="CIP Gallery",
    description="Микросервис галереи изображений. REST API + MCP (POST /mcp).",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(router)
app.include_router(mcp_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "cip-gallery"}
