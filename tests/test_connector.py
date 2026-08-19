from __future__ import annotations

import ast
import inspect
from pathlib import Path

from fivetran_connector_sdk import Logging as sdk_log

from connector import configuration_form, schema

ROOT = Path(__file__).resolve().parents[1]
LOG_METHODS = {"info", "warning", "error", "severe", "debug"}


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


def test_configuration_form_builds() -> None:
    form = configuration_form()
    assert form is not None


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
