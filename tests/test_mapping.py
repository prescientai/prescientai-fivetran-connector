from __future__ import annotations

from mapping import (
    map_channel_name,
    map_model,
    map_modeled_metric,
    map_reported_metric,
    page_info,
)


def test_modeled_metric_coalesces_null_target_channel() -> None:
    row = map_modeled_metric(
        {
            "sourceCampaignId": "camp_1",
            "sourceCampaignName": "Brand",
            "sourceChannelName": "GOOGLE_ADS",
            "reportedDate": "2026-08-01",
            "metricName": "FIRST_ORDER_REVENUE",
            "metricValue": 12.5,
            "processDate": "2026-08-18T00:00:00Z",
            "target": "new_customers",
            "targetChannelName": None,
        }
    )
    assert row["target_channel_name"] == ""
    assert row["metric_value"] == 12.5
    assert row["source_campaign_id"] == "camp_1"


def test_reported_metric_mapping() -> None:
    row = map_reported_metric(
        {
            "campaignId": "camp_1",
            "campaignName": "Brand",
            "channelName": "META",
            "processDate": "2026-08-18",
            "reportedDate": "2026-08-01",
            "spend": 40.0,
        }
    )
    assert row == {
        "campaign_id": "camp_1",
        "campaign_name": "Brand",
        "channel_name": "META",
        "reported_date": "2026-08-01",
        "process_date": "2026-08-18",
        "spend": 40.0,
    }


def test_model_and_channel_mapping() -> None:
    assert map_model({"name": "orders", "unit": "CUSTOMERS"}) == {
        "name": "orders",
        "unit": "CUSTOMERS",
    }
    assert map_channel_name("GOOGLE_ADS") == {"name": "GOOGLE_ADS"}


def test_page_info_stringifies_cursor() -> None:
    rows, cursor, has_next = page_info(
        {
            "data": [{"id": 1}],
            "pageInfo": {"endCursor": 5000, "hasNextPage": True},
        }
    )
    assert len(rows) == 1
    assert cursor == "5000"
    assert has_next is True
