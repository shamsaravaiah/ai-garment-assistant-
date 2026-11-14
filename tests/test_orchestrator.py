from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from app.agent.orchestrator import AgentOrchestrator
from app.config import Settings
from app.memory.session import SessionRecord
from app.models.schemas import IntentFilters, ProductCard


def _settings() -> Settings:
    return Settings(
        azure_openai_api_key="test",
        azure_openai_chat_deployment="chat-deploy",
        azure_search_query_key="search-key",
        azure_openai_embedding_deployment="embed-deploy",
        azure_storage_connection_string="UseDevelopmentStorage=true",
        database_url="",
        _env_file=None,
    )


@patch("app.agent.orchestrator.EmbeddingClient")
@patch("app.agent.orchestrator.SearchClient")
@patch("app.agent.orchestrator.IntentParser")
@patch("app.agent.orchestrator.AzureOpenAI")
def test_handle_chat_returns_products_from_search(
    mock_aoai: MagicMock,
    mock_intent_cls: MagicMock,
    mock_search_cls: MagicMock,
    mock_embed_cls: MagicMock,
):
    settings = _settings()
    session = SessionRecord(id=uuid.uuid4())
    memory = MagicMock()
    memory.get_or_create_session.return_value = session
    memory.load_history.return_value = []
    memory.load_filters.return_value = IntentFilters(price_max=500, currency="SEK")

    mock_intent_cls.return_value.parse.return_value = IntentFilters(
        price_max=500,
        currency="SEK",
        colors=["black"],
        garment_type="shirt",
        retrieval_query="black shirt date under 500 SEK",
        occasion=["date"],
    )
    mock_embed_cls.return_value.embed.return_value = [0.1] * 8
    mock_search_cls.return_value.search.return_value = [
        ProductCard(
            product_id="p1",
            name="Black Shirt",
            price=399,
            currency="SEK",
            image="https://cdn.example/img.jpg",
        )
    ]

    chat = MagicMock()
    chat.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="Here is a black shirt under 500 SEK."))
    ]
    mock_aoai.return_value = chat

    orch = AgentOrchestrator(settings=settings, memory=memory)
    result = orch.handle_chat("black shirt under 400 SEK for a date", top_k=3)

    assert result.session_id == session.id
    assert len(result.products) == 1
    assert result.products[0].product_id == "p1"
    assert result.needs_clarification is False
    memory.save_turn.assert_called_once()


@patch("app.agent.orchestrator.EmbeddingClient")
@patch("app.agent.orchestrator.SearchClient")
@patch("app.agent.orchestrator.IntentParser")
@patch("app.agent.orchestrator.AzureOpenAI")
def test_handle_chat_asks_clarifying_question(
    mock_aoai: MagicMock,
    mock_intent_cls: MagicMock,
    mock_search_cls: MagicMock,
    mock_embed_cls: MagicMock,
):
    settings = _settings()
    session = SessionRecord(id=uuid.uuid4())
    memory = MagicMock()
    memory.get_or_create_session.return_value = session
    memory.load_history.return_value = []
    memory.load_filters.return_value = None

    mock_intent_cls.return_value.parse.return_value = IntentFilters(
        needs_clarification=True,
        clarifying_question="Are you looking for a dress or a shirt?",
        missing_slots=["garment_type"],
        retrieval_query="something nice",
    )
    mock_aoai.return_value = MagicMock()

    orch = AgentOrchestrator(settings=settings, memory=memory)
    result = orch.handle_chat("something nice", top_k=5)

    assert result.needs_clarification is True
    assert "dress" in result.reply.lower() or "shirt" in result.reply.lower()
    assert result.products == []
    mock_embed_cls.return_value.embed.assert_not_called()
    mock_search_cls.return_value.search.assert_not_called()
    memory.save_turn.assert_called_once()
