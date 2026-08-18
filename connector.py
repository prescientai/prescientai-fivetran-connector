"""Prescient AI source connector for Fivetran Connector SDK.

Customers deploy this into their Fivetran destination and authenticate with a
Prescient API token (`Authorization: apikey <token>`). The connector reads the
public GraphQL API and upserts modeled metrics, reported spend, models, and
channel names.

See:
  https://fivetran.com/docs/connector-sdk
  https://api.prescientai.com/graphql/docs
"""

from __future__ import annotations

import json
import logging

from fivetran_connector_sdk import Connector
from fivetran_connector_sdk import Logging as log
from fivetran_connector_sdk import Operations as op
from fivetran_connector_sdk import ConfigurationForm, Test, form_field

from client import PrescientAuthError, PrescientClient, PrescientApiError
from config import (
    DEFAULT_API_URL,
    DEFAULT_START_DATE,
    SALES_CHANNEL_ALL,
    SALES_CHANNEL_ECOMMERCE,
    SALES_CHANNEL_RETAIL,
    TABLE_CHANNEL_NAMES,
    TABLE_MODELED_METRICS,
    TABLE_MODELS,
    TABLE_REPORTED_METRICS,
    ConfigError,
    ConnectorConfig,
    load_config,
)
from sync import (
    STATE_VERSION,
    sync_channel_names,
    sync_modeled_metrics,
    sync_reported_metrics,
    sync_models,
)

logging.basicConfig(level=logging.INFO)


def schema(configuration: dict) -> list[dict]:
    """Declare tables, primary keys, and types that must not be inferred.

    https://fivetran.com/docs/connector-sdk/technical-reference/connector-sdk-code/connector-sdk-methods#schema
    """
    del configuration
    return [
        {
            "table": TABLE_MODELED_METRICS,
            "primary_key": [
                "source_campaign_id",
                "source_channel_name",
                "reported_date",
                "metric_name",
                "target",
                "target_channel_name",
            ],
            "columns": {
                "source_campaign_id": "STRING",
                "source_campaign_name": "STRING",
                "source_channel_name": "STRING",
                "reported_date": "NAIVE_DATE",
                "metric_name": "STRING",
                "metric_value": "DOUBLE",
                "process_date": "UTC_DATETIME",
                "target": "STRING",
                "target_channel_name": "STRING",
            },
        },
        {
            "table": TABLE_REPORTED_METRICS,
            "primary_key": ["campaign_id", "channel_name", "reported_date"],
            "columns": {
                "campaign_id": "STRING",
                "campaign_name": "STRING",
                "channel_name": "STRING",
                "reported_date": "NAIVE_DATE",
                "process_date": "NAIVE_DATE",
                "spend": "DOUBLE",
            },
        },
        {
            "table": TABLE_MODELS,
            "primary_key": ["name"],
            "columns": {
                "name": "STRING",
                "unit": "STRING",
            },
        },
        {
            "table": TABLE_CHANNEL_NAMES,
            "primary_key": ["name"],
            "columns": {"name": "STRING"},
        },
    ]


def configuration_form() -> ConfigurationForm:
    """Fivetran dashboard setup form.

    https://fivetran.com/docs/connector-sdk/technical-reference/connector-sdk-setup-form
    """
    form = ConfigurationForm()
    form.add_field(
        form_field.TextField(
            name="api_token",
            label="Prescient API token",
            field_type=form_field.TextField.password,
            description=(
                "Generate this in Prescient under Settings → API. "
                "The header sent to the API is `Authorization: apikey <token>`."
            ),
            required=True,
        )
    )
    form.add_field(
        form_field.TextField(
            name="api_url",
            label="GraphQL endpoint",
            field_type=form_field.TextField.plain_text,
            description="Leave blank to use production.",
            required=False,
            placeholder=DEFAULT_API_URL,
        )
    )
    form.add_field(
        form_field.TextField(
            name="start_date",
            label="Historical start date",
            field_type=form_field.TextField.plain_text,
            description=(
                "Inclusive lower bound on reported_date for the initial sync "
                "(YYYY-MM-DD). Incremental syncs still send this bound so "
                "reprocessed history is picked up via processDate."
            ),
            required=False,
            placeholder=DEFAULT_START_DATE,
        )
    )
    form.add_field(
        form_field.DropdownField(
            name="sales_channel",
            label="Sales channel (modeled metrics)",
            description=(
                "Filter modeledMetrics. 'All' omits the argument, matching the "
                "API default of both ECOMMERCE and RETAIL."
            ),
            fields=[
                form_field.DropdownFieldParam(
                    value=SALES_CHANNEL_ALL,
                    label="All",
                    description="Do not filter; returns every sales channel.",
                ),
                form_field.DropdownFieldParam(
                    value=SALES_CHANNEL_ECOMMERCE,
                    label="Ecommerce",
                ),
                form_field.DropdownFieldParam(
                    value=SALES_CHANNEL_RETAIL,
                    label="Retail",
                ),
            ],
            required=False,
        )
    )
    form.add_field(
        form_field.ToggleField(
            name="sync_modeled_metrics",
            label="Sync modeled metrics",
            description="Attribution output from modeledMetrics.",
        )
    )
    form.add_field(
        form_field.ToggleField(
            name="sync_reported_metrics",
            label="Sync reported metrics",
            description="Campaign spend from reportedMetrics.",
        )
    )
    form.add_field(
        form_field.ToggleField(
            name="sync_models",
            label="Sync models",
            description="Available model names and units.",
        )
    )
    form.add_field(
        form_field.ToggleField(
            name="sync_channel_names",
            label="Sync channel names",
            description="Distinct source channel names.",
        )
    )
    form.add_test(label="Test API connection", func=_connection_test)
    return form


def _connection_test(configuration: dict) -> Test:
    test = Test()
    try:
        config = load_config(configuration)
        PrescientClient(config.api_url, config.api_token).probe()
    except (ConfigError, PrescientAuthError, PrescientApiError) as exc:
        return test.failure(str(exc))
    return test.success()


def _upsert(table: str, data: dict) -> None:
    op.upsert(table=table, data=data)


def _checkpoint(state: dict) -> None:
    op.checkpoint(state=state)


def _truncate(table: str) -> None:
    op.truncate(table=table)


def update(configuration: dict, state: dict) -> None:
    """Called by Fivetran at the start of each sync.

    https://fivetran.com/docs/connector-sdk/technical-reference/connector-sdk-code/connector-sdk-methods#update
    """
    try:
        config = load_config(configuration)
    except ConfigError as exc:
        op.error(str(exc))
        return

    state = dict(state or {})
    state["version"] = STATE_VERSION

    client = PrescientClient(config.api_url, config.api_token)
    try:
        log.info("Probing Prescient API at %s", config.api_url)
        client.probe()
        _run_sync(client, config, state)
    except PrescientAuthError as exc:
        op.error(str(exc), trace=str(exc))
    except PrescientApiError as exc:
        op.error(f"Prescient API error: {exc}", trace=str(exc))


def _run_sync(
    client: PrescientClient,
    config: ConnectorConfig,
    state: dict,
) -> None:
    enabled = set(config.enabled_tables())
    log.info("Enabled tables: %s", ", ".join(config.enabled_tables()))

    if TABLE_MODELS in enabled:
        sync_models(
            client,
            state,
            upsert=_upsert,
            truncate=_truncate,
            checkpoint=_checkpoint,
        )
    if TABLE_CHANNEL_NAMES in enabled:
        sync_channel_names(
            client,
            state,
            upsert=_upsert,
            truncate=_truncate,
            checkpoint=_checkpoint,
        )
    if TABLE_MODELED_METRICS in enabled:
        sync_modeled_metrics(
            client,
            config,
            state,
            upsert=_upsert,
            checkpoint=_checkpoint,
            truncate=_truncate,
        )
    if TABLE_REPORTED_METRICS in enabled:
        sync_reported_metrics(
            client,
            config,
            state,
            upsert=_upsert,
            checkpoint=_checkpoint,
            truncate=_truncate,
        )

    _checkpoint(state)
    log.info("Sync completed")


connector = Connector(
    update=update,
    schema=schema,
    configuration_form=configuration_form,
)

if __name__ == "__main__":
    with open("configuration.json", encoding="utf-8") as handle:
        connector.debug(configuration=json.load(handle))
