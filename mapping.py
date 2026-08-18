"""Map GraphQL rows onto destination columns.

Primary keys use snake_case names that survive Fivetran's renaming rules.
`target_channel_name` is coalesced to empty string so the modeled-metrics
composite key never includes SQL NULL (Fivetran cannot upsert on a null PK).
"""

from __future__ import annotations

from typing import Any


def coalesce_pk(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def map_modeled_metric(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_campaign_id": coalesce_pk(row.get("sourceCampaignId")),
        "source_campaign_name": row.get("sourceCampaignName"),
        "source_channel_name": coalesce_pk(row.get("sourceChannelName")),
        "reported_date": coalesce_pk(row.get("reportedDate")),
        "metric_name": coalesce_pk(row.get("metricName")),
        "metric_value": row.get("metricValue"),
        "process_date": row.get("processDate"),
        "target": coalesce_pk(row.get("target")),
        "target_channel_name": coalesce_pk(row.get("targetChannelName")),
    }


def map_reported_metric(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "campaign_id": coalesce_pk(row.get("campaignId")),
        "campaign_name": row.get("campaignName"),
        "channel_name": coalesce_pk(row.get("channelName")),
        "reported_date": coalesce_pk(row.get("reportedDate")),
        "process_date": row.get("processDate"),
        "spend": row.get("spend"),
    }


def map_model(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": coalesce_pk(row.get("name")),
        "unit": row.get("unit"),
    }


def map_channel_name(name: str) -> dict[str, Any]:
    return {"name": coalesce_pk(name)}


def page_info(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None, bool]:
    rows = payload.get("data") or []
    if not isinstance(rows, list):
        rows = []
    info = payload.get("pageInfo") or {}
    end_cursor = info.get("endCursor")
    if end_cursor is not None:
        end_cursor = str(end_cursor)
    has_next = bool(info.get("hasNextPage"))
    return rows, end_cursor, has_next
