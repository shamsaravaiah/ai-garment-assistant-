from __future__ import annotations

from typing import Any

from azure.data.tables import TableServiceClient
from fastapi import APIRouter
from openai import AzureOpenAI
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.models.schemas import HealthResponse
from app.retrieval.search import SearchClient

router = APIRouter(tags=["health"])


@router.get("/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    checks: dict[str, Any] = {}

    # Azure Table Storage chat memory
    try:
        if not settings.resolved_storage_connection_string:
            checks["chat_memory"] = {
                "ok": False,
                "error": "missing AZURE_STORAGE_CONNECTION_STRING",
            }
        else:
            svc = TableServiceClient.from_connection_string(
                settings.resolved_storage_connection_string
            )
            list(svc.list_tables())
            checks["chat_memory"] = {"ok": True, "backend": "azure_table_storage"}
    except Exception as exc:  # noqa: BLE001
        checks["chat_memory"] = {"ok": False, "error": str(exc)}

    if settings.catalog_db_enabled:
        try:
            engine = create_engine(settings.database_url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["catalog_postgres"] = {"ok": True}
        except Exception as exc:  # noqa: BLE001
            checks["catalog_postgres"] = {"ok": False, "error": str(exc)}
    else:
        checks["catalog_postgres"] = {
            "ok": True,
            "skipped": True,
            "detail": "DATABASE_URL not set; using Azure AI Search fields only",
        }

    try:
        if not settings.search_api_key:
            checks["azure_search"] = {"ok": False, "error": "missing api key"}
        else:
            ok = SearchClient(settings).ping()
            checks["azure_search"] = {"ok": ok}
    except Exception as exc:  # noqa: BLE001
        checks["azure_search"] = {"ok": False, "error": str(exc)}

    try:
        if not settings.azure_openai_api_key:
            checks["azure_openai"] = {"ok": False, "error": "missing api key"}
        elif not settings.azure_openai_chat_deployment:
            checks["azure_openai"] = {
                "ok": False,
                "error": "missing AZURE_OPENAI_CHAT_DEPLOYMENT",
            }
        else:
            AzureOpenAI(
                api_key=settings.azure_openai_api_key,
                api_version=settings.azure_openai_api_version,
                azure_endpoint=settings.azure_openai_endpoint,
            )
            checks["azure_openai"] = {
                "ok": True,
                "chat_deployment": settings.azure_openai_chat_deployment,
                "embedding_deployment": settings.azure_openai_embedding_deployment,
            }
    except Exception as exc:  # noqa: BLE001
        checks["azure_openai"] = {"ok": False, "error": str(exc)}

    required_ok = all(
        checks[name].get("ok")
        for name in ("chat_memory", "azure_search", "azure_openai")
    )
    status = "ok" if required_ok else "degraded"
    return HealthResponse(status=status, checks=checks)
