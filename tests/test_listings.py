"""Tests for own_listings extraction helpers."""

from __future__ import annotations

from lth_api import SharetribeFlexAPI


def test_extract_listing_returns_simplified_dict():
    images_map = {"img-1": "https://cdn/img1.jpg"}
    raw = {
        "id": {"uuid": "list-1"},
        "type": "ownListing",
        "attributes": {
            "title": "6x4 Cage Trailer",
            "state": "published",
            "deleted": False,
            "price": {"amount": 5500, "currency": "AUD"},
        },
        "relationships": {"images": {"data": [{"id": {"uuid": "img-1"}}]}},
    }
    result = SharetribeFlexAPI._extract_listing(raw, images_map)
    assert result == {
        "id": "list-1",
        "title": "6x4 Cage Trailer",
        "state": "published",
        "deleted": False,
        "price_aud": 55.0,
        "image_url": "https://cdn/img1.jpg",
    }


def test_extract_listing_returns_none_without_id():
    assert SharetribeFlexAPI._extract_listing({"id": {}}, {}) is None
    assert SharetribeFlexAPI._extract_listing({}, {}) is None


def test_extract_listing_handles_missing_image():
    raw = {
        "id": {"uuid": "list-2"},
        "attributes": {"title": "Box Trailer", "state": "closed"},
        "relationships": {},
    }
    result = SharetribeFlexAPI._extract_listing(raw, {})
    assert result is not None
    assert result["image_url"] is None
    assert result["state"] == "closed"


def test_build_images_map_prefers_landscape_crop2x():
    included = [
        {
            "id": {"uuid": "img-x"},
            "type": "image",
            "attributes": {
                "variants": {
                    "default": {"url": "https://cdn/default.jpg"},
                    "landscape-crop2x": {"url": "https://cdn/2x.jpg"},
                    "landscape-crop": {"url": "https://cdn/1x.jpg"},
                }
            },
        }
    ]
    images_map = SharetribeFlexAPI._build_images_map(included)
    assert images_map == {"img-x": "https://cdn/2x.jpg"}


def test_build_images_map_falls_back_to_any_variant():
    included = [
        {
            "id": {"uuid": "img-y"},
            "type": "image",
            "attributes": {
                "variants": {"weird-variant": {"url": "https://cdn/weird.jpg"}}
            },
        }
    ]
    images_map = SharetribeFlexAPI._build_images_map(included)
    assert images_map == {"img-y": "https://cdn/weird.jpg"}


def test_build_images_map_skips_non_images():
    included = [{"id": {"uuid": "x"}, "type": "user", "attributes": {}}]
    assert SharetribeFlexAPI._build_images_map(included) == {}
