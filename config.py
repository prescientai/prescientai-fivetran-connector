"""Parse and validate Connector SDK configuration.

Fivetran always supplies configuration values as strings. See
https://fivetran.com/docs/connector-sdk/connector-development-and-configuration/configuration-json
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse
import re

DEFAULT_API_URL = "https://api.prescientai.com/graphql"
DEFAULT_START_DATE = "2018-01-01"
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SALES_CHANNEL_ALL = "all"
SALES_CHANNEL_ECOMMERCE = "ECOMMERCE"
SALES_CHANNEL_RETAIL = "RETAIL"
VALID_SALES_CHANNELS = frozenset(
    {SALES_CHANNEL_ALL, SALES_CHANNEL_ECOMMERCE, SALES_CHANNEL_RETAIL}
)

TABLE_MODELED_METRICS = "modeled_metrics"
TABLE_REPORTED_METRICS = "reported_metrics"
TABLE_MODELS = "models"
TABLE_CHANNEL_NAMES = "channel_names"
ALL_TABLES = (
    TABLE_MODELED_METRICS,
    TABLE_REPORTED_METRICS,
    TABLE_MODELS,
    TABLE_CHANNEL_NAMES,
)


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


def as_bool(value: str | None, default: bool = True) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"true", "1", "yes", "on"}


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def parse_iso_date(value: str, field_name: str) -> str:
    if not ISO_DATE_RE.match(value):
        raise ConfigError(f"{field_name} must be YYYY-MM-DD, got {value!r}")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ConfigError(f"{field_name} is not a valid date: {value!r}") from exc
    return value


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    return host.lower() in {"localhost", "127.0.0.1", "::1"}


def normalize_api_url(value: str | None) -> str:
    url = (value or "").strip() or DEFAULT_API_URL
    url = url.rstrip("/")
    if not url.endswith("/graphql"):
        url = f"{url}/graphql"
    parsed = urlparse(url)
    if parsed.scheme == "https":
        return url
    if parsed.scheme == "http" and _is_loopback_host(parsed.hostname):
        return url
    raise ConfigError(
        "api_url must use https://. http:// is only allowed for localhost "
        "(local debug)."
    )


@dataclass(frozen=True)
class ConnectorConfig:
    api_token: str
    api_url: str
    start_date: str
    sales_channels: tuple[str, ...] | None
    sync_modeled_metrics: bool
    sync_reported_metrics: bool
    sync_models: bool
    sync_channel_names: bool

    def enabled_tables(self) -> tuple[str, ...]:
        tables: list[str] = []
        if self.sync_modeled_metrics:
            tables.append(TABLE_MODELED_METRICS)
        if self.sync_reported_metrics:
            tables.append(TABLE_REPORTED_METRICS)
        if self.sync_models:
            tables.append(TABLE_MODELS)
        if self.sync_channel_names:
            tables.append(TABLE_CHANNEL_NAMES)
        return tuple(tables)

    def metric_scope(self, table: str) -> dict[str, Any]:
        """JSON-serializable fingerprint of filters that change incremental meaning."""
        scope: dict[str, Any] = {"start_date": self.start_date}
        if table == TABLE_MODELED_METRICS:
            scope["sales_channels"] = (
                list(self.sales_channels)
                if self.sales_channels
                else [SALES_CHANNEL_ALL]
            )
        return scope


def load_config(configuration: dict) -> ConnectorConfig:
    token = (configuration.get("api_token") or "").strip()
    if not token:
        raise ConfigError("Missing required configuration value: 'api_token'")

    start_date = parse_iso_date(
        (configuration.get("start_date") or DEFAULT_START_DATE).strip(),
        "start_date",
    )

    sales_raw = (configuration.get("sales_channel") or SALES_CHANNEL_ALL).strip()
    if sales_raw not in VALID_SALES_CHANNELS:
        raise ConfigError(
            "sales_channel must be one of: all, ECOMMERCE, RETAIL. "
            f"Got {sales_raw!r}."
        )
    sales_channels = None if sales_raw == SALES_CHANNEL_ALL else (sales_raw,)

    config = ConnectorConfig(
        api_token=token,
        api_url=normalize_api_url(configuration.get("api_url")),
        start_date=start_date,
        sales_channels=sales_channels,
        sync_modeled_metrics=as_bool(configuration.get("sync_modeled_metrics")),
        sync_reported_metrics=as_bool(configuration.get("sync_reported_metrics")),
        sync_models=as_bool(configuration.get("sync_models")),
        sync_channel_names=as_bool(configuration.get("sync_channel_names")),
    )
    if not config.enabled_tables():
        raise ConfigError("At least one table must be enabled for sync.")
    return config
