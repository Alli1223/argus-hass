"""A small client for the parts of the Argus HTTP API this integration reads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)


class ArgusError(Exception):
    """Argus could not be read."""


class ArgusConnectionError(ArgusError):
    """The server could not be reached, or answered with something other than Argus's API."""


class ArgusAuthError(ArgusError):
    """The token was refused: wrong, revoked, its owner disabled, or a server too old for tokens."""


class ArgusClient:
    """Reads one Argus server with a read-only API token."""

    def __init__(self, session: aiohttp.ClientSession, url: str, token: str) -> None:
        self._session = session
        self.url = normalize_url(url)
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        try:
            async with self._session.get(
                f"{self.url}{path}", headers=self._headers, params=params, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status in (401, 403):
                    raise ArgusAuthError(f"Argus refused the token ({response.status})")
                if response.status != 200:
                    raise ArgusConnectionError(f"{path} answered {response.status}")
                # Raises ContentTypeError, a ClientError, when the answer is not JSON: not an Argus server.
                return await response.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ArgusConnectionError(f"Could not reach {self.url}: {err}") from err

    async def get_info(self) -> dict[str, Any]:
        """The server's name, version and public address."""
        return await self._get("/api/info")

    async def get_me(self) -> dict[str, Any]:
        """The person the token belongs to."""
        return await self._get("/api/auth/me")

    async def get_hosts(self) -> list[dict[str, Any]]:
        """Every host the token's owner can see, with its status and latest readings."""
        return await self._get("/api/hosts")

    async def get_firing_alerts(self) -> list[dict[str, Any]]:
        """Alerts firing now."""
        page = await self._get("/api/alerts", {"status": "Firing", "pageSize": "200"})
        return page["items"]

    async def get_containers(self) -> list[dict[str, Any]]:
        """Every host that reports containers, with its containers."""
        return await self._get("/api/containers")

    async def get_temperatures(self, window: timedelta) -> list[dict[str, Any]]:
        """Each host's temperature history over the last `window`."""
        now = datetime.now(UTC)
        return await self._get(
            "/api/hosts/temperatures",
            {"from": (now - window).isoformat(), "to": now.isoformat(), "points": "10"},
        )


def normalize_url(url: str) -> str:
    """The server's base address without a trailing slash."""
    return url.strip().rstrip("/")


def latest_temperatures(history: dict[str, Any]) -> dict[str, float]:
    """The newest reading of each sensor in a temperature history, by `{device}/{sensor}` key."""
    readings: dict[str, float] = {}
    for key, values in history.get("series", {}).items():
        for value in reversed(values):
            if value is not None:
                readings[key] = round(value, 1)
                break
    return readings
