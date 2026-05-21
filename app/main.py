"""FastAPI app: chat, cabinet API, static pages."""
import logging
import sys
import traceback
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException

# Логи приложения (сброс пароля, отправка писем и т.д.) в stderr — видны в docker logs
_app_log = logging.getLogger("app")
_app_log.setLevel(logging.INFO)
if not _app_log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("%(levelname)s: %(name)s: %(message)s"))
    _app_log.addHandler(_h)
_app_log.propagate = False
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.routers import auth, chat, cabinet
from app.services.cabinet_service import get_tenant_by_slug

app = FastAPI(title="CIP Backend", description="Chat + User Cabinet API")


@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    """В ответе 500 возвращаем текст ошибки для отладки."""
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "type": type(exc).__name__,
            "traceback": traceback.format_exc(),
        },
    )

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(cabinet.router)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
STATIC_DIR.mkdir(exist_ok=True)


@app.get("/static/index.html")
async def block_static_index():
    """Страницы index нет — вход только через /{tenant_slug}/login или /register."""
    raise HTTPException(status_code=404, detail="Not found")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/register")
async def serve_register_standalone() -> FileResponse:
    """Регистрация «один тенант на пользователя»: без slug, создаётся новый тенант."""
    path = STATIC_DIR / "register.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="register page not found")
    return FileResponse(path)


@app.get("/{slug}/chat")
async def serve_chat(slug: str, db: AsyncSession = Depends(get_db)) -> FileResponse:
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    chat_path = STATIC_DIR / "chat.html"
    if not chat_path.exists():
        raise HTTPException(status_code=404, detail="chat page not found")
    return FileResponse(chat_path)


@app.get("/{slug}/chat/embed")
async def serve_chat_embed(slug: str, db: AsyncSession = Depends(get_db)) -> FileResponse:
    """Чат для вставки в iframe на сторонних сайтах."""
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    chat_path = STATIC_DIR / "chat.html"
    if not chat_path.exists():
        raise HTTPException(status_code=404, detail="chat page not found")
    return FileResponse(chat_path)


@app.get("/{slug}/my")
@app.get("/{slug}/my/{path:path}")
async def serve_cabinet(slug: str, path: str = "", db: AsyncSession = Depends(get_db)) -> FileResponse:
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    cabinet_path = STATIC_DIR / "cabinet.html"
    if not cabinet_path.exists():
        raise HTTPException(status_code=404, detail="cabinet page not found")
    return FileResponse(cabinet_path, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@app.get("/{slug}/register")
async def serve_register(slug: str, db: AsyncSession = Depends(get_db)) -> FileResponse:
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    path = STATIC_DIR / "register.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="register page not found")
    return FileResponse(path)


@app.get("/login")
async def serve_login_standalone() -> FileResponse:
    """Вход без указания тенанта в URL: обезличенная форма, тенант определяется по email."""
    path = STATIC_DIR / "login.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="login page not found")
    return FileResponse(path)


@app.get("/{slug}/login")
async def serve_login(slug: str, db: AsyncSession = Depends(get_db)) -> FileResponse:
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    path = STATIC_DIR / "login.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="login page not found")
    return FileResponse(path)


@app.get("/{slug}/confirm")
async def serve_confirm(slug: str, db: AsyncSession = Depends(get_db)) -> FileResponse:
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    path = STATIC_DIR / "confirm.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="confirm page not found")
    return FileResponse(path)


@app.get("/{slug}/forgot-password")
async def serve_forgot_password(slug: str, db: AsyncSession = Depends(get_db)) -> FileResponse:
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    path = STATIC_DIR / "forgot-password.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="forgot-password page not found")
    return FileResponse(path)


@app.get("/{slug}/reset-password")
async def serve_reset_password(slug: str, db: AsyncSession = Depends(get_db)) -> FileResponse:
    tenant = await get_tenant_by_slug(db, slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    path = STATIC_DIR / "reset-password.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="reset-password page not found")
    return FileResponse(path)


@app.get("/")
async def root():
    """Отдельной главной страницы нет. Редирект на обезличенную страницу входа."""
    return RedirectResponse(url="/login", status_code=302)
