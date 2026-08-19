from __future__ import annotations

import pytest

from config import (
    DEFAULT_API_URL,
    ConfigError,
    load_config,
)


def _base(**overrides: str) -> dict[str, str]:
    values = {
        "api_token": "tok_live",
        "api_url": DEFAULT_API_URL,
        "start_date": "2020-01-01",
        "sales_channel": "all",
    }
    values.update(overrides)
    return values


def test_requires_api_token() -> None:
    with pytest.raises(ConfigError, match="api_token"):
        load_config({"api_token": "  "})


def test_normalizes_api_url_without_graphql_suffix() -> None:
    config = load_config(_base(api_url="https://api.prescient-ai.io"))
    assert config.api_url == DEFAULT_API_URL


def test_rejects_plaintext_remote_http() -> None:
    with pytest.raises(ConfigError, match="https"):
        load_config(_base(api_url="http://api.prescient-ai.io/graphql"))


def test_allows_http_loopback_for_local_debug() -> None:
    config = load_config(_base(api_url="http://localhost:7100/graphql"))
    assert config.api_url == "http://localhost:7100/graphql"


def test_rejects_missing_scheme() -> None:
    with pytest.raises(ConfigError, match="https"):
        load_config(_base(api_url="api.prescient-ai.io/graphql"))


def test_invalid_start_date() -> None:
    with pytest.raises(ConfigError, match="start_date"):
        load_config(_base(start_date="01-01-2020"))


def test_sales_channel_all_means_unfiltered() -> None:
    config = load_config(_base(sales_channel="all"))
    assert config.sales_channels is None


def test_sales_channel_retail() -> None:
    config = load_config(_base(sales_channel="RETAIL"))
    assert config.sales_channels == ("RETAIL",)


def test_invalid_sales_channel() -> None:
    with pytest.raises(ConfigError, match="sales_channel"):
        load_config(_base(sales_channel="wholesale"))


def test_tables_default_on() -> None:
    config = load_config(_base())
    assert config.enabled_tables() == (
        "modeled_metrics",
        "reported_metrics",
        "models",
        "channel_names",
    )


def test_can_disable_tables() -> None:
    config = load_config(
        _base(
            sync_modeled_metrics="false",
            sync_reported_metrics="false",
            sync_models="true",
            sync_channel_names="0",
        )
    )
    assert config.enabled_tables() == ("models",)


def test_rejects_all_tables_disabled() -> None:
    with pytest.raises(ConfigError, match="At least one table"):
        load_config(
            _base(
                sync_modeled_metrics="false",
                sync_reported_metrics="false",
                sync_models="false",
                sync_channel_names="false",
            )
        )
