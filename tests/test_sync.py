from __future__ import annotations

import copy
from typing import Any

import pytest

from config import load_config
from sync import (
    sync_channel_names,
    sync_modeled_metrics,
    sync_models,
    table_state,
)


class FakeClient:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self.pages = list(pages)
        self.calls: list[dict[str, Any]] = []
        self.model_rows = [{"name": "orders", "unit": "CUSTOMERS"}]
        self.channels = ["GOOGLE_ADS", "META"]

    def modeled_metrics(self, **kwargs):
        self.calls.append(kwargs)
        if not self.pages:
            raise AssertionError("Unexpected modeled_metrics call")
        return self.pages.pop(0)

    def models(self):
        return self.model_rows

    def channel_names(self):
        return self.channels


def _config(**overrides: str):
    values = {
        "api_token": "tok",
        "start_date": "2020-01-01",
        "sales_channel": "all",
    }
    values.update(overrides)
    return load_config(values)


def test_paginates_and_checkpoints_after_each_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sync.utc_today", lambda: "2026-08-18")
    client = FakeClient(
        [
            {
                "data": [
                    {
                        "sourceCampaignId": "a",
                        "sourceChannelName": "GOOGLE_ADS",
                        "reportedDate": "2026-08-01",
                        "metricName": "FIRST_ORDER_REVENUE",
                        "metricValue": 1,
                        "processDate": "2026-08-02T00:00:00Z",
                        "target": "orders",
                        "targetChannelName": None,
                    }
                ],
                "pageInfo": {"endCursor": "99", "hasNextPage": True},
            },
            {
                "data": [
                    {
                        "sourceCampaignId": "b",
                        "sourceChannelName": "META",
                        "reportedDate": "2026-08-01",
                        "metricName": "FIRST_ORDER_REVENUE",
                        "metricValue": 2,
                        "processDate": "2026-08-03T00:00:00Z",
                        "target": "orders",
                        "targetChannelName": None,
                    }
                ],
                "pageInfo": {"endCursor": "100", "hasNextPage": False},
            },
        ]
    )
    upserts: list[tuple[str, dict[str, Any]]] = []
    checkpoints: list[dict[str, Any]] = []

    sync_modeled_metrics(
        client,  # type: ignore[arg-type]
        _config(),
        {},
        upsert=lambda table, row: upserts.append((table, row)),
        checkpoint=lambda state: checkpoints.append(copy.deepcopy(state)),
    )

    assert len(upserts) == 2
    assert upserts[0][0] == "modeled_metrics"
    assert len(checkpoints) == 2
    mid = table_state(checkpoints[0], "modeled_metrics")
    assert mid["after"] == "99"
    assert mid.get("process_date") is None
    done = table_state(checkpoints[-1], "modeled_metrics")
    assert done["after"] is None
    assert done["process_date"] == "2026-08-18"
    assert client.calls[0]["after"] is None
    assert client.calls[0]["process_date"] is None
    assert client.calls[1]["after"] == "99"


def test_incremental_uses_stored_process_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sync.utc_today", lambda: "2026-08-19")
    client = FakeClient(
        [
            {
                "data": [],
                "pageInfo": {"endCursor": None, "hasNextPage": False},
            }
        ]
    )
    state = {
        "tables": {
            "modeled_metrics": {
                "after": None,
                "process_date": "2026-08-18",
            }
        }
    }
    sync_modeled_metrics(
        client,  # type: ignore[arg-type]
        _config(),
        state,
        upsert=lambda *_args: None,
        checkpoint=lambda *_args: None,
    )
    assert client.calls[0]["process_date"] == "2026-08-18"
    assert client.calls[0]["start_date"] == "2020-01-01"
    assert client.calls[0]["end_date"] == "2026-08-19"


def test_resume_keeps_window_and_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sync.utc_today", lambda: "2026-08-20")
    client = FakeClient(
        [
            {
                "data": [],
                "pageInfo": {"endCursor": None, "hasNextPage": False},
            }
        ]
    )
    state = {
        "tables": {
            "modeled_metrics": {
                "after": "123",
                "process_date": "2026-08-10",
                "window_start": "2020-01-01",
                "window_end": "2026-08-18",
                "window_process_date": "2026-08-10",
            }
        }
    }
    sync_modeled_metrics(
        client,  # type: ignore[arg-type]
        _config(),
        state,
        upsert=lambda *_args: None,
        checkpoint=lambda *_args: None,
    )
    assert client.calls[0]["after"] == "123"
    assert client.calls[0]["process_date"] == "2026-08-10"
    assert client.calls[0]["end_date"] == "2026-08-18"


def test_scope_change_truncates_and_drops_process_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sync.utc_today", lambda: "2026-08-19")
    client = FakeClient(
        [{"data": [], "pageInfo": {"endCursor": None, "hasNextPage": False}}]
    )
    truncated: list[str] = []
    state = {
        "tables": {
            "modeled_metrics": {
                "after": "99",
                "process_date": "2026-08-18",
                "window_start": "2020-01-01",
                "window_end": "2026-08-18",
                "window_process_date": "2026-08-18",
                "scope": {
                    "start_date": "2020-01-01",
                    "sales_channels": ["all"],
                },
            }
        }
    }
    sync_modeled_metrics(
        client,  # type: ignore[arg-type]
        _config(start_date="2018-01-01"),
        state,
        upsert=lambda *_args: None,
        checkpoint=lambda *_args: None,
        truncate=lambda table: truncated.append(table),
    )
    assert truncated == ["modeled_metrics"]
    assert client.calls[0]["after"] is None
    assert client.calls[0]["process_date"] is None
    assert client.calls[0]["start_date"] == "2018-01-01"
    assert table_state(state, "modeled_metrics")["scope"]["start_date"] == "2018-01-01"


def test_sales_channel_change_is_a_scope_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sync.utc_today", lambda: "2026-08-19")
    client = FakeClient(
        [{"data": [], "pageInfo": {"endCursor": None, "hasNextPage": False}}]
    )
    truncated: list[str] = []
    state = {
        "tables": {
            "modeled_metrics": {
                "process_date": "2026-08-18",
                "scope": {
                    "start_date": "2020-01-01",
                    "sales_channels": ["all"],
                },
            }
        }
    }
    sync_modeled_metrics(
        client,  # type: ignore[arg-type]
        _config(sales_channel="RETAIL"),
        state,
        upsert=lambda *_args: None,
        checkpoint=lambda *_args: None,
        truncate=lambda table: truncated.append(table),
    )
    assert truncated == ["modeled_metrics"]
    assert client.calls[0]["process_date"] is None
    assert client.calls[0]["sales_channels"] == ("RETAIL",)


def test_dimension_tables_truncate_then_upsert() -> None:
    client = FakeClient([])
    ops: list[tuple[str, Any]] = []

    sync_models(
        client,  # type: ignore[arg-type]
        {},
        upsert=lambda table, row: ops.append(("upsert", table, row)),
        truncate=lambda table: ops.append(("truncate", table)),
        checkpoint=lambda _state: ops.append(("checkpoint",)),
    )
    sync_channel_names(
        client,  # type: ignore[arg-type]
        {},
        upsert=lambda table, row: ops.append(("upsert", table, row)),
        truncate=lambda table: ops.append(("truncate", table)),
        checkpoint=lambda _state: ops.append(("checkpoint",)),
    )

    assert ops[0] == ("truncate", "models")
    assert ops[1][0] == "upsert" and ops[1][2]["name"] == "orders"
    assert ops[3] == ("truncate", "channel_names")
    assert {ops[4][2]["name"], ops[5][2]["name"]} == {"GOOGLE_ADS", "META"}
