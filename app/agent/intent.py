from __future__ import annotations

import json
from typing import Any

from openai import AzureOpenAI

from app.agent.prompts import INTENT_SYSTEM_PROMPT
from app.config import Settings
from app.models.schemas import ChatMessageOut, IntentFilters


class IntentParser:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = AzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
        )

    def parse(
        self,
        user_message: str,
        history: list[ChatMessageOut],
        prior_filters: IntentFilters | None,
    ) -> IntentFilters:
        history_blob = [
            {"role": m.role, "content": m.content}
            for m in history[-6:]
            if m.role in ("user", "assistant")
        ]
        prior = prior_filters.model_dump() if prior_filters else {}
        user_payload = {
            "message": user_message,
            "prior_filters": prior,
            "recent_history": history_blob,
        }
        response = self._client.chat.completions.create(
            model=self.settings.azure_openai_chat_deployment,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload)},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        data = self._safe_json(raw)
        parsed = IntentFilters.model_validate(data)
        if not parsed.retrieval_query:
            parsed.retrieval_query = user_message.strip()
        if prior_filters:
            merged = prior_filters.merge(parsed)
        else:
            merged = parsed
        return self._apply_clarification_guardrails(merged, user_message, history)

    def _apply_clarification_guardrails(
        self,
        filters: IntentFilters,
        user_message: str,
        history: list[ChatMessageOut],
    ) -> IntentFilters:
        # Stop clarifying loops after two assistant questions without products.
        prior_questions = sum(
            1
            for m in history[-8:]
            if m.role == "assistant" and not m.products
        )
        if prior_questions >= 2:
            filters.needs_clarification = False
            filters.clarifying_question = None
            filters.missing_slots = []
            return filters

        # Enough signal to search — don't block.
        if filters.specificity_score() >= 3:
            filters.needs_clarification = False
            filters.clarifying_question = None
            filters.missing_slots = []
            return filters

        # Very short / vague message with little structured intent.
        words = [w for w in user_message.strip().split() if w]
        vague = len(words) <= 4 and filters.specificity_score() < 2
        if vague and not filters.needs_clarification:
            filters.needs_clarification = True
            filters.missing_slots = filters.missing_slots or [
                "garment_type",
                "occasion",
            ]
            filters.clarifying_question = filters.clarifying_question or (
                "Happy to help — are you looking for a dress, shirt, trousers, "
                "or a full outfit? And is this for a date, work, or everyday wear?"
            )

        if filters.needs_clarification and not filters.clarifying_question:
            filters.clarifying_question = (
                "Could you tell me what kind of item you want "
                "(for example dress, shirt, or jeans) and any color or budget?"
            )
        return filters

    @staticmethod
    def _safe_json(raw: str) -> dict[str, Any]:
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
