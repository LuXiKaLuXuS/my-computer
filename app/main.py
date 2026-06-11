from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.logging_config import configure_logging, get_logger
from app.middleware.metrics import PrometheusMiddleware, metrics_endpoint
from app.middleware.rate_limit import limiter
from app.routers import api_keys, auth, goals, health, memory, meta, projects, webhooks

settings = get_settings()
configure_logging(settings.debug)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app_starting", version=settings.app_version)
    yield
    logger.info("app_stopping")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(PrometheusMiddleware)

app.include_router(health.router)
app.include_router(auth.router, prefix="/api")
app.include_router(api_keys.router, prefix="/api")
app.include_router(goals.router, prefix="/api")
app.include_router(memory.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(webhooks.router, prefix="/api")
app.include_router(meta.router, prefix="/api")

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
        "metrics": "/metrics",
    }


@app.get("/ui")
async def ui():
    return FileResponse("static/index.html")


@app.get("/metrics")
@limiter.exempt
async def metrics(request: Request):
    return metrics_endpoint()