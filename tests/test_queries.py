from __future__ import annotations

from queries import (
    CHANNEL_NAMES_QUERY,
    MODELED_METRICS_QUERY,
    MODELS_QUERY,
    REPORTED_METRICS_QUERY,
)


def test_queries_select_contract_fields() -> None:
    assert "modeledMetrics" in MODELED_METRICS_QUERY
    assert "sourceCampaignName" in MODELED_METRICS_QUERY
    assert "$after: BigInt" in MODELED_METRICS_QUERY
    assert "reportedMetrics" in REPORTED_METRICS_QUERY
    assert "campaignName" in REPORTED_METRICS_QUERY
    assert "models {" in MODELS_QUERY
    assert "channelNames" in CHANNEL_NAMES_QUERY
