"""Constants for the Argus integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "argus"

CONF_SCAN_INTERVAL: Final = "scan_interval"
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 3600

# Temperatures are read from the last few minutes of history; the newest reading of each sensor wins.
TEMPERATURE_WINDOW: Final = timedelta(minutes=5)

EVENT_ALERT_FIRED: Final = "argus_alert_fired"
EVENT_ALERT_RESOLVED: Final = "argus_alert_resolved"

TOKEN_PREFIX: Final = "argus_at_"
