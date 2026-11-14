from __future__ import annotations

import json
import uuid

from openai import AzureOpenAI

from app.agent.intent import IntentParser
from app.agent.prompts import REPLY_SYSTEM_PROMPT
from app.config import Settings, get_settings
from app.db import get_catalog_session
from app.memory.store import MemoryStore
from app.models.schemas import ChatResponse, IntentFilters, ProductCard
from app.retrieval.embeddings import EmbeddingClient
from app.retrieval.hydrate import ProductHydrator
from app.retrieval.search import SearchClient


class AgentOrchestrator:
    def __init__(
        self,
        settings: Settings | None = None,
        memory: MemoryStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.memory = memory or MemoryStore()
        self.intent = IntentParser(self.settings)
        self.embeddings = EmbeddingClient(self.settings)
        self.search = SearchClient(self.settings)
        self._chat = AzureOpenAI(
            api_key=self.settings.azure_openai_api_key,
            api_version=self.settings.azure_openai_api_version,
            azure_endpoint=self.settings.azure_openai_endpoint,
        )

    def handle_chat(
        self,
        message: str,
        session_id: uuid.UUID | None = None,
        top_k: int | None = None,
    ) -> ChatResponse:
        k = top_k or self.settings.default_top_k
        k = max(1, min(k, self.settings.max_top_k))

        session = self.memory.get_or_create_session(session_id)
        history = self.memory.load_history(session.id)
        prior_filters = self.memory.load_filters(session)

        filters = self.intent.parse(message, history, prior_filters)

        # Ask a clarifying question instead of searching when intent is too vague.
        if filters.needs_clarification and filters.clarifying_question:
            reply = filters.clarifying_question.strip()
            products: list[ProductCard] = []
            self.memory.save_turn(
                session=session,
                user_message=message,
                assistant_reply=reply,
                products=products,
                filters=filters,
            )
            return ChatResponse(
                session_id=session.id,
                reply=reply,
                products=products,
                filters_applied=filters,
                needs_clarification=True,
            )

        retrieval_text = filters.retrieval_query or message
        vector = self.embeddings.embed(retrieval_text)
        products = self.search.search(
            vector=vector,
            filters=filters,
            top_k=k,
            text_query=retrieval_text,
        )
        products = self._maybe_hydrate(products)
        reply = self._compose_reply(message, filters, products, history)

        self.memory.save_turn(
            session=session,
            user_message=message,
            assistant_reply=reply,
            products=products,
            filters=filters,
        )
        return ChatResponse(
            session_id=session.id,
            reply=reply,
            products=products,
            filters_applied=filters,
            needs_clarification=False,
        )

    def _maybe_hydrate(self, products: list[ProductCard]) -> list[ProductCard]:
        if not self.settings.catalog_db_enabled or not products:
            return products
        catalog_db = get_catalog_session()
        if catalog_db is None:
            return products
        try:
            return ProductHydrator(catalog_db).hydrate(products)
        except Exception:
            return products
        finally:
            catalog_db.close()

    def _compose_reply(
        self,
        user_message: str,
        filters: IntentFilters,
        products: list[ProductCard],
        history: list,
    ) -> str:
        product_payload = [p.model_dump(mode="json") for p in products]
        messages = [
            {"role": "system", "content": REPLY_SYSTEM_PROMPT},
        ]
        for m in history[-4:]:
            if m.role in ("user", "assistant"):
                messages.append({"role": m.role, "content": m.content})
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_message": user_message,
                        "filters_applied": filters.model_dump(mode="json"),
                        "products": product_payload,
                    }
                ),
            }
        )
        response = self._chat.chat.completions.create(
            model=self.settings.azure_openai_chat_deployment,
            temperature=0.4,
            messages=messages,
        )
        return (response.choices[0].message.content or "").strip() or (
            "Here are some options I found for you."
            if products
            else "I could not find matching products. Try adjusting your budget or style."
        )
