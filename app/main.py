from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.routes_chat import router as chat_router
from app.api.routes_health import router as health_router
from app.config import get_settings
from app.memory.store import MemoryStore
from app.rate_limit import limiter

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Ensure chat tables exist when storage is configured.
    # Do not crash the process on transient storage init errors.
    if settings.resolved_storage_connection_string:
        try:
            MemoryStore()
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: chat memory init deferred: {exc}")
    yield


app = FastAPI(
    title="Catalog Shopping Agent",
    description="Multi-turn fashion catalog assistant with Azure AI Search retrieval",
    version="0.2.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

cors_origins = settings.cors_origins or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if "*" in cors_origins else cors_origins,
    allow_credentials=False if "*" in cors_origins else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(health_router)

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
if UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=UI_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(UI_DIR / "index.html")
