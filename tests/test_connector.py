from __future__ import annotations

from connector import configuration_form, schema


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
