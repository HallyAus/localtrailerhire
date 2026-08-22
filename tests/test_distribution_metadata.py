"""Validate the metadata and brand assets used to distribute the integration."""

from __future__ import annotations

import json
import struct
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT = REPO_ROOT / "custom_components" / "localtrailerhire"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_size(path: Path) -> tuple[int, int]:
    """Return the dimensions stored in a PNG's IHDR chunk."""
    with path.open("rb") as image:
        assert image.read(8) == PNG_SIGNATURE
        assert image.read(4) == b"\x00\x00\x00\r"
        assert image.read(4) == b"IHDR"
        return struct.unpack(">II", image.read(8))


def test_hacs_repository_install_configuration() -> None:
    """Custom HACS repositories install directly from the repository tree."""
    hacs = json.loads((REPO_ROOT / "hacs.json").read_text(encoding="utf-8"))

    assert hacs["name"] == "Local Trailer Hire"
    assert "zip_release" not in hacs
    assert "filename" not in hacs


def test_manifest_has_hacs_required_fields() -> None:
    """Keep the integration manifest eligible for HACS validation."""
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["domain"] == COMPONENT.name
    for key in (
        "codeowners",
        "documentation",
        "domain",
        "issue_tracker",
        "name",
        "version",
    ):
        assert manifest.get(key), f"manifest.json is missing {key}"


def test_local_brand_assets_match_home_assistant_dimensions() -> None:
    """Catch missing or incorrectly sized local brand files before release."""
    icon_width, icon_height = _png_size(COMPONENT / "brand" / "icon.png")
    logo_width, logo_height = _png_size(COMPONENT / "brand" / "logo.png")
    dark_logo_width, dark_logo_height = _png_size(COMPONENT / "brand" / "dark_logo.png")

    assert (icon_width, icon_height) == (256, 256)
    for width, height in (
        (logo_width, logo_height),
        (dark_logo_width, dark_logo_height),
    ):
        assert width > height
        assert 128 <= min(width, height) <= 256
