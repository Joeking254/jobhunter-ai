from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api.routes.health import router as health_router
from app.api.routes.auth import router as auth_router
from app.api.routes.profile import router as profile_router
from app.api.routes.documents import router as documents_router
from app.api.routes.sources import router as sources_router
from app.api.routes.matching import router as matching_router
from app.api.routes.generation import router as generation_router
from app.api.routes.applications import router as applications_router
from app.api.routes.bot import router as bot_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.interviews import router as interviews_router
from app.api.routes.monitoring import router as monitoring_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.opportunities import router as opportunities_router
from app.api.routes.searches import router as searches_router
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if settings.app_env.lower() == "production" else "/docs",
    redoc_url=None if settings.app_env.lower() == "production" else "/redoc",
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path.startswith("/api/auth"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(profile_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(sources_router, prefix="/api")
app.include_router(matching_router, prefix="/api")
app.include_router(generation_router, prefix="/api")
app.include_router(applications_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(opportunities_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(interviews_router, prefix="/api")
app.include_router(searches_router, prefix="/api")
app.include_router(bot_router, prefix="/api")
app.include_router(monitoring_router, prefix="/api")
