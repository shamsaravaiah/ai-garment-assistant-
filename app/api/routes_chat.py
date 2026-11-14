from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request

from app.agent.orchestrator import AgentOrchestrator
from app.config import get_settings
from app.memory.store import MemoryStore
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    SessionHistoryResponse,
)
from app.rate_limit import CHAT_RATE_LIMIT, limiter

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
@limiter.limit(CHAT_RATE_LIMIT)
def chat(request: Request, body: ChatRequest) -> ChatResponse:
    settings = get_settings()
    if not settings.azure_openai_chat_deployment:
        raise HTTPException(
            status_code=500,
            detail="AZURE_OPENAI_CHAT_DEPLOYMENT is not configured",
        )
    if not settings.search_api_key:
        raise HTTPException(
            status_code=500,
            detail="Azure Search API key is not configured",
        )
    if not settings.azure_openai_api_key:
        raise HTTPException(
            status_code=500,
            detail="AZURE_OPENAI_API_KEY is not configured",
        )
    if not settings.resolved_storage_connection_string:
        raise HTTPException(
            status_code=500,
            detail="AZURE_STORAGE_CONNECTION_STRING is not configured",
        )

    orchestrator = AgentOrchestrator(settings=settings)
    return orchestrator.handle_chat(
        message=body.message.strip(),
        session_id=body.session_id,
        top_k=body.top_k,
    )


@router.get("/sessions/{session_id}", response_model=SessionHistoryResponse)
def get_session(session_id: uuid.UUID) -> SessionHistoryResponse:
    store = MemoryStore()
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    filters = store.load_filters(session)
    return SessionHistoryResponse(
        session_id=session.id,
        summary=session.summary,
        filters=filters,
        messages=store.load_history(session.id),
    )


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: uuid.UUID) -> None:
    store = MemoryStore()
    if not store.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
