from __future__ import annotations

import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.models.schemas import ChatResponse, IntentFilters, ProductCard


def _test_settings() -> Settings:
    return Settings(
        azure_openai_api_key="test-key",
        azure_openai_chat_deployment="chat-deploy",
        azure_search_query_key="search-key",
        azure_openai_embedding_deployment="embed-deploy",
        azure_storage_connection_string="DefaultEndpointsProtocol=https;AccountName=x;AccountKey=dGVzdA==;EndpointSuffix=core.windows.net",
        database_url="",
        cors_origins=["http://testserver"],
        _env_file=None,
    )


@patch("app.main.MemoryStore")
def test_chat_endpoint_ok(mock_memory_cls):
    from app.main import app

    mock_memory_cls.return_value = object()
    session_id = uuid.uuid4()
    fake = ChatResponse(
        session_id=session_id,
        reply="Found a few options.",
        products=[
            ProductCard(
                product_id="abc",
                name="Shirt",
                price=299,
                currency="SEK",
                image="https://example.com/a.jpg",
                url="https://example.com/p/abc",
            )
        ],
        filters_applied=IntentFilters(
            price_max=400, currency="SEK", retrieval_query="black shirt"
        ),
        needs_clarification=False,
    )

    with (
        patch("app.api.routes_chat.get_settings", _test_settings),
        patch("app.api.routes_chat.AgentOrchestrator") as orch_cls,
    ):
        orch_cls.return_value.handle_chat.return_value = fake
        client = TestClient(app)
        res = client.post(
            "/v1/chat",
            json={"message": "black shirt under 400 SEK for a date", "top_k": 5},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["session_id"] == str(session_id)
    assert len(body["products"]) == 1


@patch("app.main.MemoryStore")
def test_health_endpoint_shape(mock_memory_cls):
    from app.main import app

    mock_memory_cls.return_value = object()
    with patch("app.api.routes_health.get_settings", _test_settings):
        with patch("app.api.routes_health.TableServiceClient") as table_cls:
            table_cls.from_connection_string.return_value.list_tables.return_value = []
            with patch("app.api.routes_health.SearchClient") as search_cls:
                search_cls.return_value.ping.return_value = True
                client = TestClient(app)
                res = client.get("/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert "status" in body
    assert "checks" in body
