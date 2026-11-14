from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class SessionRecord:
    id: uuid.UUID
    summary: str | None = None
    filters_json: dict | None = field(default=None)
