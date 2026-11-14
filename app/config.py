from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _parse_cors_origins(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [part.strip() for part in text.split(",") if part.strip()]
    return [str(value)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    azure_search_endpoint: str = Field(
        default="https://search-catalog-product-description-vectors.search.windows.net"
    )
    azure_search_query_key: str = ""
    azure_search_admin_key: str = ""
    azure_search_index_name: str = "products-vectors"

    azure_openai_endpoint: str = Field(
        default="https://oai-catalog-product-description-vision-embed.openai.azure.com/"
    )
    azure_openai_api_key: str = ""
    azure_openai_api_version: str = "2024-12-01-preview"
    azure_openai_embedding_deployment: str = (
        "deploy-text-embedding-3-small-product-vectors"
    )
    azure_openai_embedding_dimensions: int = 1536
    azure_openai_chat_deployment: str = ""

    # Optional catalog Postgres hydrate.
    database_url: str = ""

    # Azure Table Storage for multi-turn chat memory (cheaper than Cosmos DB).
    azure_storage_connection_string: str = ""
    # Prefer this in Container Apps: connection strings contain '=' / ';' which
    # break --secrets name=value parsing. Store base64(conn) instead.
    azure_storage_connection_string_b64: str = ""

    default_top_k: int = 5
    max_top_k: int = 10
    chat_history_limit: int = 12
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "*",
        ]
    )
    rate_limit_per_minute: int = 60

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors(cls, value: object) -> list[str]:
        return _parse_cors_origins(value)

    @property
    def search_api_key(self) -> str:
        return self.azure_search_query_key or self.azure_search_admin_key

    @property
    def resolved_storage_connection_string(self) -> str:
        # Prefer B64 in Container Apps — plain connection strings often get
        # truncated at ';' when passed through secret name=value parsing.
        encoded = self.azure_storage_connection_string_b64.strip()
        if encoded:
            import base64

            return base64.b64decode(encoded).decode("utf-8")
        return self.azure_storage_connection_string.strip()

    @property
    def catalog_db_enabled(self) -> bool:
        return bool(self.database_url.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
