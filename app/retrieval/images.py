from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_OVERLAY_RE = re.compile(r"/overlay/|overlay\d+|placeholder|presentkort", re.I)
_PRIVATE_BLOB_RE = re.compile(r"\.blob\.core\.windows\.net", re.I)
_GIFT_RE = re.compile(r"presentkort|gift\s*card|present\s*card", re.I)


def normalize_image_url(url: str | None) -> str | None:
    """Fix common CDN URL bugs (extra '?') and trim."""
    if not url or not isinstance(url, str):
        return None
    text = url.strip()
    if not text:
        return None
    # johnells-style: ...jpg?timestamp=123?extend=white → second ? should be &
    if text.count("?") > 1:
        first, rest = text.split("?", 1)
        text = first + "?" + rest.replace("?", "&")
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return urlunsplit(parts)


def is_private_blob(url: str | None) -> bool:
    return bool(url and _PRIVATE_BLOB_RE.search(url))


def is_usable_product_image(url: str | None) -> bool:
    if not url:
        return False
    if is_private_blob(url):
        return False
    if _OVERLAY_RE.search(url):
        return False
    return True


def pick_product_image(source_url: str | None, blob_url: str | None = None) -> str | None:
    """Prefer public CDN source_url; never expose private blob URLs to the UI."""
    for candidate in (source_url,):
        normalized = normalize_image_url(candidate)
        if is_usable_product_image(normalized):
            return normalized
    # blob_url is private without SAS — skip for browser rendering
    _ = blob_url
    return None


def looks_like_gift_card(name: str | None, description: str | None = None) -> bool:
    blob = f"{name or ''} {description or ''}"
    return bool(_GIFT_RE.search(blob))
