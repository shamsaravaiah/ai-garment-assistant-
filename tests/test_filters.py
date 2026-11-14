from app.config import Settings, _parse_cors_origins
from app.models.schemas import IntentFilters
from app.retrieval.search import SearchClient


def test_parse_cors_comma_separated():
    assert _parse_cors_origins("http://localhost:8000,http://127.0.0.1:8000") == [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]


def test_parse_cors_json_array():
    assert _parse_cors_origins('["http://localhost:8000"]') == ["http://localhost:8000"]


def test_settings_accepts_comma_cors(monkeypatch):
    monkeypatch.setenv(
        "CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
    )
    settings = Settings(_env_file=None)
    assert settings.cors_origins == [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]


def test_intent_merge_preserves_budget():
    prior = IntentFilters(price_max=500, currency="SEK", occasion=["date"])
    newer = IntentFilters(
        colors=["black"],
        garment_type="shirt",
        retrieval_query="black shirt date night",
        needs_clarification=False,
    )
    merged = prior.merge(newer)
    assert merged.price_max == 500
    assert merged.currency == "SEK"
    assert merged.occasion == ["date"]
    assert merged.colors == ["black"]
    assert merged.garment_type == "shirt"
    assert "black shirt" in merged.retrieval_query
    assert merged.needs_clarification is False


def test_specificity_score():
    filters = IntentFilters(
        occasion=["date"], garment_type="dress", colors=["black"], price_max=500
    )
    assert filters.specificity_score() >= 3


def test_build_filter_price_and_currency():
    client = SearchClient(Settings(_env_file=None))
    filters = IntentFilters(price_max=400, currency="SEK", gender="women")
    odata = client.build_filter(filters, include_tags=False, exclude_non_apparel=False)
    assert odata is not None
    assert "price le 400" in odata
    assert "currency eq 'SEK'" in odata
    assert "gender eq 'women'" in odata


def test_build_filter_expands_date_occasion():
    client = SearchClient(Settings(_env_file=None))
    filters = IntentFilters(price_max=500, currency="SEK", occasion=["date"])
    odata = client.build_filter(filters, include_tags=True, exclude_non_apparel=False)
    assert odata is not None
    assert "occasion/any" in odata
    assert "date" in odata
    assert "evening" in odata


def test_build_filter_rejects_unsafe_tokens():
    client = SearchClient(Settings(_env_file=None))
    filters = IntentFilters(currency="SEK'; DROP TABLE products;--")
    odata = client.build_filter(filters, include_tags=False, exclude_non_apparel=False)
    assert odata is None or "DROP" not in odata
    if odata:
        assert "currency" not in odata
