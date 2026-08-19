"""Incremental sync helpers.

Modeled and reported metrics use the API's `processDate` filter — the contract
recommends it so callers skip unchanged history. Pagination cursors are stored
in Fivetran state so a failed long sync can resume mid-page.

Dimension tables (`models`, `channel_names`) are small; they are truncated and
fully replaced each sync so removals show up as `_fivetran_deleted`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
import logging

from client import PrescientClient
from config import (
    TABLE_CHANNEL_NAMES,
    TABLE_MODELED_METRICS,
    TABLE_MODELS,
    TABLE_REPORTED_METRICS,
    ConnectorConfig,
    utc_today,
)
from mapping import (
    map_channel_name,
    map_model,
    map_modeled_metric,
    map_reported_metric,
    page_info,
)

log = logging.getLogger("prescient.fivetran")

Upsert = Callable[[str, dict[str, Any]], None]
Checkpoint = Callable[[dict[str, Any]], None]
Truncate = Callable[[str], None]

STATE_VERSION = 1


def table_state(state: dict[str, Any], table: str) -> dict[str, Any]:
    tables = state.setdefault("tables", {})
    current = tables.get(table)
    if not isinstance(current, dict):
        current = {}
        tables[table] = current
    return current


def sync_modeled_metrics(
    client: PrescientClient,
    config: ConnectorConfig,
    state: dict[str, Any],
    *,
    upsert: Upsert,
    checkpoint: Checkpoint,
    truncate: Truncate | None = None,
) -> None:
    _sync_metric_pages(
        table=TABLE_MODELED_METRICS,
        config=config,
        state=state,
        upsert=upsert,
        checkpoint=checkpoint,
        truncate=truncate,
        fetch=lambda after, process_date, start_date, end_date: client.modeled_metrics(
            start_date=start_date,
            end_date=end_date,
            process_date=process_date,
            after=after,
            sales_channels=config.sales_channels,
        ),
        mapper=map_modeled_metric,
    )


def sync_reported_metrics(
    client: PrescientClient,
    config: ConnectorConfig,
    state: dict[str, Any],
    *,
    upsert: Upsert,
    checkpoint: Checkpoint,
    truncate: Truncate | None = None,
) -> None:
    _sync_metric_pages(
        table=TABLE_REPORTED_METRICS,
        config=config,
        state=state,
        upsert=upsert,
        checkpoint=checkpoint,
        truncate=truncate,
        fetch=lambda after, process_date, start_date, end_date: client.reported_metrics(
            start_date=start_date,
            end_date=end_date,
            process_date=process_date,
            after=after,
        ),
        mapper=map_reported_metric,
    )


def _sync_metric_pages(
    *,
    table: str,
    config: ConnectorConfig,
    state: dict[str, Any],
    upsert: Upsert,
    checkpoint: Checkpoint,
    fetch: Callable[[str | None, str | None, str, str], dict[str, Any]],
    mapper: Callable[[dict[str, Any]], dict[str, Any]],
    truncate: Truncate | None = None,
) -> None:
    current = table_state(state, table)
    fingerprint = config.metric_scope(table)
    stored_scope = current.get("scope")
    if stored_scope is not None and stored_scope != fingerprint:
        log.info(
            f"Sync scope changed for {table} ({stored_scope} -> {fingerprint}); full resync"
        )
        if truncate is not None:
            truncate(table)
        current.clear()
    current["scope"] = fingerprint

    end_date = utc_today()
    after = current.get("after") or None
    # Resume an interrupted sync with the same processDate/window that produced
    # `after`. A fresh pass uses the last completed process_date as the filter.
    if after:
        start_date = current.get("window_start") or config.start_date
        end_date = current.get("window_end") or end_date
        process_date = current.get("window_process_date")
    else:
        start_date = config.start_date
        process_date = current.get("process_date") or None
        current["window_start"] = start_date
        current["window_end"] = end_date
        current["window_process_date"] = process_date

    log.info(
        f"Syncing {table} start_date={start_date} end_date={end_date} "
        f"process_date={process_date} after={after}"
    )

    page_count = 0
    row_count = 0
    while True:
        payload = fetch(after, process_date, start_date, end_date)
        rows, end_cursor, has_next = page_info(payload)
        for row in rows:
            upsert(table, mapper(row))
        page_count += 1
        row_count += len(rows)

        if has_next and end_cursor:
            after = end_cursor
            current["after"] = after
            checkpoint(state)
            continue

        current["after"] = None
        current["process_date"] = end_date
        current["scope"] = fingerprint
        current.pop("window_start", None)
        current.pop("window_end", None)
        current.pop("window_process_date", None)
        checkpoint(state)
        log.info(
            f"Finished {table} ({page_count} pages, {row_count} rows). "
            f"Next process_date={end_date}"
        )
        return


def sync_models(
    client: PrescientClient,
    state: dict[str, Any],
    *,
    upsert: Upsert,
    truncate: Truncate,
    checkpoint: Checkpoint,
) -> None:
    rows = client.models()
    truncate(TABLE_MODELS)
    for row in rows:
        upsert(TABLE_MODELS, map_model(row))
    table_state(state, TABLE_MODELS)["synced_at"] = utc_today()
    checkpoint(state)
    log.info(f"Finished {TABLE_MODELS} ({len(rows)} rows)")


def sync_channel_names(
    client: PrescientClient,
    state: dict[str, Any],
    *,
    upsert: Upsert,
    truncate: Truncate,
    checkpoint: Checkpoint,
) -> None:
    names = client.channel_names()
    truncate(TABLE_CHANNEL_NAMES)
    for name in names:
        upsert(TABLE_CHANNEL_NAMES, map_channel_name(name))
    table_state(state, TABLE_CHANNEL_NAMES)["synced_at"] = utc_today()
    checkpoint(state)
    log.info(f"Finished {TABLE_CHANNEL_NAMES} ({len(names)} rows)")
