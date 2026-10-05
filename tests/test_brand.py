"""The integration brings its own icon, which Home Assistant 2026.3 and later show."""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from custom_components.argus.const import DOMAIN


async def test_ships_its_own_icon(hass: HomeAssistant) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    brand = Path(integration.file_path) / "brand"

    assert (brand / "icon.png").is_file()
    assert (brand / "icon@2x.png").is_file()
    # Older releases have no local branding and use the brands repository instead.
    if hasattr(integration, "has_branding"):
        assert integration.has_branding
