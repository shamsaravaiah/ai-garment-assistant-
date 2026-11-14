from __future__ import annotations

from openai import AzureOpenAI

from app.config import Settings


class EmbeddingClient:
    """Query embeddings only — never uses the vision enrichment deployment."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = AzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
        )

    def embed(self, text: str) -> list[float]:
        response = self._client.embeddings.create(
            input=text,
            model=self.settings.azure_openai_embedding_deployment,
            dimensions=self.settings.azure_openai_embedding_dimensions,
        )
        return list(response.data[0].embedding)
