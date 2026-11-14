from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.data.tables import TableClient, TableServiceClient, UpdateMode

from app.config import get_settings
from app.memory.session import SessionRecord
from app.models.schemas import ChatMessageOut, IntentFilters, ProductCard

SESSIONS_TABLE = "chatsessions"
MESSAGES_TABLE = "chatmessages"


class MemoryStore:
    """Chat memory backed by Azure Table Storage (cheaper than Cosmos for this use)."""

    def __init__(self, connection_string: str | None = None) -> None:
        self.settings = get_settings()
        conn = connection_string or self.settings.resolved_storage_connection_string
        if not conn:
            raise RuntimeError(
                "AZURE_STORAGE_CONNECTION_STRING is required for chat memory"
            )
        self._service = TableServiceClient.from_connection_string(conn)
        self._sessions = self._get_or_create_table(SESSIONS_TABLE)
        self._messages = self._get_or_create_table(MESSAGES_TABLE)

    def _get_or_create_table(self, name: str) -> TableClient:
        try:
            self._service.create_table(name)
        except ResourceExistsError:
            pass
        return self._service.get_table_client(name)

    def get_or_create_session(self, session_id: uuid.UUID | None) -> SessionRecord:
        if session_id is not None:
            existing = self.get_session(session_id)
            if existing is not None:
                return existing
        sid = session_id or uuid.uuid4()
        now = datetime.now(timezone.utc).isoformat()
        entity = {
            "PartitionKey": "session",
            "RowKey": str(sid),
            "summary": None,
            "filters_json": None,
            "created_at": now,
            "updated_at": now,
        }
        self._sessions.upsert_entity(entity=entity, mode=UpdateMode.REPLACE)
        return SessionRecord(id=sid)

    def get_session(self, session_id: uuid.UUID) -> SessionRecord | None:
        try:
            entity = self._sessions.get_entity(
                partition_key="session", row_key=str(session_id)
            )
        except ResourceNotFoundError:
            return None
        filters_raw = entity.get("filters_json")
        filters_json = None
        if filters_raw:
            try:
                filters_json = json.loads(filters_raw)
            except json.JSONDecodeError:
                filters_json = None
        return SessionRecord(
            id=session_id,
            summary=entity.get("summary"),
            filters_json=filters_json,
        )

    def delete_session(self, session_id: uuid.UUID) -> bool:
        session = self.get_session(session_id)
        if session is None:
            return False
        # Delete messages first.
        for entity in self._messages.query_entities(
            query_filter=f"PartitionKey eq '{session_id}'"
        ):
            self._messages.delete_entity(
                partition_key=entity["PartitionKey"], row_key=entity["RowKey"]
            )
        self._sessions.delete_entity(partition_key="session", row_key=str(session_id))
        return True

    def load_history(self, session_id: uuid.UUID) -> list[ChatMessageOut]:
        limit = self.settings.chat_history_limit
        rows = list(
            self._messages.query_entities(
                query_filter=f"PartitionKey eq '{session_id}'"
            )
        )
        rows.sort(key=lambda e: e.get("created_at") or e.get("RowKey") or "")
        rows = rows[-limit:]
        out: list[ChatMessageOut] = []
        for row in rows:
            products = None
            raw_products = row.get("products_json")
            if raw_products:
                try:
                    parsed = json.loads(raw_products)
                    products = [ProductCard.model_validate(p) for p in parsed]
                except (json.JSONDecodeError, ValueError):
                    products = None
            out.append(
                ChatMessageOut(
                    role=row.get("role", "assistant"),  # type: ignore[arg-type]
                    content=row.get("content") or "",
                    products=products,
                    created_at=row.get("created_at"),
                )
            )
        return out

    def load_filters(self, session: SessionRecord) -> IntentFilters | None:
        if not session.filters_json:
            return None
        return IntentFilters.model_validate(session.filters_json)

    def save_turn(
        self,
        session: SessionRecord,
        user_message: str,
        assistant_reply: str,
        products: list[ProductCard],
        filters: IntentFilters,
        summary: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        products_payload: list[dict[str, Any]] = [
            p.model_dump(mode="json") for p in products
        ]
        self._messages.create_entity(
            {
                "PartitionKey": str(session.id),
                "RowKey": f"{now.strftime('%Y%m%d%H%M%S%f')}-u-{uuid.uuid4().hex[:8]}",
                "role": "user",
                "content": user_message,
                "products_json": None,
                "created_at": now.isoformat(),
            }
        )
        self._messages.create_entity(
            {
                "PartitionKey": str(session.id),
                "RowKey": f"{now.strftime('%Y%m%d%H%M%S%f')}-a-{uuid.uuid4().hex[:8]}",
                "role": "assistant",
                "content": assistant_reply,
                "products_json": json.dumps(products_payload),
                "created_at": now.isoformat(),
            }
        )
        session.filters_json = filters.model_dump(mode="json")
        if summary is not None:
            session.summary = summary
        self._sessions.upsert_entity(
            {
                "PartitionKey": "session",
                "RowKey": str(session.id),
                "summary": session.summary,
                "filters_json": json.dumps(session.filters_json),
                "updated_at": now.isoformat(),
            },
            mode=UpdateMode.MERGE,
        )
