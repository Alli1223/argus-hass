"""Shared fixtures: a fake Argus server answering through Home Assistant's aiohttp mock."""

from __future__ import annotations

import copy
from typing import Any

from homeassistant.const import CONF_API_TOKEN, CONF_URL, CONF_VERIFY_SSL
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.argus.const import DOMAIN

URL = "https://argus.example.com"
TOKEN = "argus_at_" + "a" * 43
USER_ID = "6f1d1c43-0a51-4f4b-9b7e-3b6f6f0b6a11"
HOST_ID = "0d4f0b5e-2d7c-4a43-8b0e-5d5b9f2c7a01"
OTHER_HOST_ID = "8a2c3e44-6b1f-4f7a-9c0d-1e2f3a4b5c02"

INFO = {"name": "Argus", "version": "0.9.0", "publicUrl": URL}
ME = {"id": USER_ID, "email": "me@example.com", "displayName": "Me", "roles": ["Admin"], "isAdmin": True}

HOST = {
    "id": HOST_ID,
    "displayName": "homeassistant",
    "hostname": "homeassistant",
    "platform": "Linux",
    "osName": "Home Assistant OS 16.2",
    "tags": [],
    "status": "Online",
    "lastSeenAt": "2026-10-05T10:00:00+00:00",
    "agentVersion": "0.9.0",
    "ownerId": USER_ID,
    "latest": {
        "time": "2026-10-05T10:00:00+00:00",
        "cpuPercent": 12.345,
        "memoryPercent": 41.27,
        "memoryUsedBytes": 1_700_000_000,
        "memoryTotalBytes": 4_100_000_000,
        "swapPercent": None,
        "load1": 0.4567,
        "diskUsedPercent": 63.04,
        "netRxBytesPerSec": 125_000.4,
        "netTxBytesPerSec": 25_000.0,
        "uptimeSeconds": 7230,
    },
    "agentUpdate": None,
}

ALERT = {
    "id": "a1",
    "ruleId": "r1",
    "ruleName": "Hot CPU",
    "hostId": HOST_ID,
    "hostName": "homeassistant",
    "resourceKey": "",
    "title": "CPU usage above 90% on homeassistant",
    "metric": "CpuUsage",
    "condition": "Threshold",
    "operator": "Above",
    "threshold": 90.0,
    "severity": "Warning",
    "status": "Firing",
    "value": 95.0,
    "baseline": None,
    "firedAt": "2026-10-05T09:58:00+00:00",
    "resolvedAt": None,
    "acknowledgedAt": None,
    "acknowledgedBy": None,
}

CONTAINERS = [
    {
        "hostId": HOST_ID,
        "hostName": "homeassistant",
        "checkedAt": "2026-10-05T10:00:00+00:00",
        "problem": None,
        "actionsEnabled": False,
        "containers": [
            {
                "name": "homeassistant",
                "state": "running",
                "health": "healthy",
                "image": "ghcr.io/home-assistant/raspberrypi4-64-homeassistant",
                "restartsLastHour": 0,
            },
            {
                "name": "addon_argus_agent",
                "state": "exited",
                "health": None,
                "image": "ghcr.io/alli1223/argus-agent",
                "restartsLastHour": 2,
            },
        ],
    }
]

TEMPERATURES = [
    {
        "hostId": HOST_ID,
        "displayName": "homeassistant",
        "history": {
            "from": "2026-10-05T09:55:00+00:00",
            "to": "2026-10-05T10:00:00+00:00",
            "resolution": "raw",
            "bucketSeconds": 30,
            "time": [1, 2, 3],
            "series": {"cpu_thermal/temp1": [51.0, 52.04, None], "nvme0/Composite": [38.0, None, 39.96]},
        },
    }
]


class FakeArgus:
    """What the mocked server answers; tests change these and refresh."""

    def __init__(self) -> None:
        self.hosts: list[dict[str, Any]] = [copy.deepcopy(HOST)]
        self.alerts: list[dict[str, Any]] = [copy.deepcopy(ALERT)]
        self.containers = copy.deepcopy(CONTAINERS)
        self.temperatures = copy.deepcopy(TEMPERATURES)
        self.status = 200

    def install(self, mocker: AiohttpClientMocker) -> None:
        mocker.clear_requests()
        if self.status != 200:
            for path in ("info", "auth/me", "hosts", "alerts", "containers", "hosts/temperatures"):
                mocker.get(f"{URL}/api/{path}", status=self.status)
            return
        mocker.get(f"{URL}/api/info", json=INFO)
        mocker.get(f"{URL}/api/auth/me", json=ME)
        mocker.get(f"{URL}/api/hosts/temperatures", json=self.temperatures)
        mocker.get(f"{URL}/api/hosts", json=self.hosts)
        mocker.get(
            f"{URL}/api/alerts", json={"items": self.alerts, "total": len(self.alerts), "page": 1, "pageSize": 200}
        )
        mocker.get(f"{URL}/api/containers", json=self.containers)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Lets Home Assistant load custom_components/argus."""


@pytest.fixture
def argus(aioclient_mock: AiohttpClientMocker) -> FakeArgus:
    fake = FakeArgus()
    fake.install(aioclient_mock)
    return fake


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Argus (argus.example.com)",
        unique_id=f"{URL}|{USER_ID}",
        data={CONF_URL: URL, CONF_API_TOKEN: TOKEN, CONF_VERIFY_SSL: True},
    )
