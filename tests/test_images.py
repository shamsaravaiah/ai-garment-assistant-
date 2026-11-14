from app.retrieval.images import (
    looks_like_gift_card,
    normalize_image_url,
    pick_product_image,
)


def test_normalize_double_query():
    raw = (
        "https://www.johnells.se/pub_images/original/x.jpg"
        "?timestamp=1791210366?extend=white&width=360"
    )
    fixed = normalize_image_url(raw)
    assert fixed is not None
    assert fixed.count("?") == 1
    assert "?timestamp=1791210366&extend=white" in fixed


def test_pick_skips_overlay_and_blob():
    assert (
        pick_product_image(
            "https://www.johnells.se/M1/production/images/overlay/overlay6_sv-SE.png",
            "https://ingimg725829.blob.core.windows.net/catalog-images/x.jpg",
        )
        is None
    )


def test_pick_prefers_source_url():
    url = "https://cdn.example/product.jpg"
    assert pick_product_image(url, "https://ingimg725829.blob.core.windows.net/x.jpg") == url


def test_gift_card_detection():
    assert looks_like_gift_card("Digitalt presentkort 500")
    assert not looks_like_gift_card("Anja Dress")
