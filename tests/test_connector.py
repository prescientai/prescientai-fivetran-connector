from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from fivetran_connector_sdk import Logging as sdk_log
from fivetran_connector_sdk import form_field

from connector import configuration_form, connection_test, schema

ROOT = Path(__file__).resolve().parents[1]
LOG_METHODS = {"info", "warning", "error", "severe", "debug", "critical"}


def test_schema_declares_tables_and_primary_keys() -> None:
    tables = {entry["table"]: entry for entry in schema({})}
    assert set(tables) == {
        "modeled_metrics",
        "reported_metrics",
        "models",
        "channel_names",
    }
    assert "source_campaign_id" in tables["modeled_metrics"]["primary_key"]
    assert tables["reported_metrics"]["primary_key"] == [
        "campaign_id",
        "channel_name",
        "reported_date",
    ]
    assert tables["modeled_metrics"]["columns"]["reported_date"] == "NAIVE_DATE"
    assert tables["modeled_metrics"]["columns"]["process_date"] == "UTC_DATETIME"


def test_configuration_form_matches_sdk_contract() -> None:
    form = configuration_form()
    fields = {field.name: field for field in form._fields}
    assert list(fields) == [
        "api_token",
        "api_url",
        "start_date",
        "sales_channel",
        "sync_modeled_metrics",
        "sync_reported_metrics",
        "sync_models",
        "sync_channel_names",
    ]
    assert fields["api_token"].required is True
    assert fields["api_token"].text_field == form_field.TextField.password
    assert fields["api_url"].required is False
    assert fields["api_url"].text_field == form_field.TextField.plain_text
    assert fields["sales_channel"].required is True
    assert fields["sync_modeled_metrics"].HasField("toggle_field")
    labels_and_names = [(label, func.__name__) for label, func in form._tests]
    assert labels_and_names == [("Test API connection", "connection_test")]


def test_connection_test_does_not_require_table_toggles() -> None:
    result = connection_test({"api_token": ""})
    assert result.failure == "Missing required configuration value: 'api_token'"


def test_sdk_logging_takes_a_single_message() -> None:
    params = list(inspect.signature(sdk_log.info).parameters)
    assert params == ["message"]
    params = list(inspect.signature(sdk_log.warning).parameters)
    assert params == ["message"]


def test_project_log_calls_pass_a_single_message() -> None:
    """Fivetran Logging.info(message) does not accept stdlib printf extra args."""
    violations = []
    for path in ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr not in LOG_METHODS:
                continue
            if not isinstance(func.value, ast.Name) or func.value.id != "log":
                continue
            if len(node.args) != 1:
                violations.append(f"{path.name}:{node.lineno} {ast.unparse(node)}")
    assert violations == []


def test_update_reports_failures_with_a_dashboard_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str | None] = {}

    class BoomClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def probe(self) -> None:
            raise RuntimeError("probe exploded")

    def fake_error(*, message: str, trace: str | None = None) -> None:
        captured["message"] = message
        captured["trace"] = trace

    monkeypatch.setattr("connector.PrescientClient", BoomClient)
    monkeypatch.setattr("connector.op.error", fake_error)
    monkeypatch.setattr("connector.log.critical", lambda _message: None)

    from connector import update

    update({"api_token": "tok"}, {})
    assert captured["message"] == "probe exploded"
    assert captured["trace"] and "RuntimeError" in captured["trace"]
