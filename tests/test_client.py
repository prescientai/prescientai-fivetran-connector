from __future__ import annotations

import json
from typing import Any

import pytest
import requests

from client import (
    AUTH_FAILED_MESSAGE,
    PrescientApiError,
    PrescientAuthError,
    PrescientClient,
    PrescientTransientError,
    compact_variables,
    graphql,
)
from queries import MODELS_QUERY


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        json_body: Any = None,
        headers: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self._json = json_body
        self.headers = headers or {}
        self.text = ""

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(
            {"url": url, "json": json, "headers": headers, "timeout": timeout}
        )
        if not self._responses:
            raise AssertionError("Unexpected extra HTTP call")
        return self._responses.pop(0)


def test_compact_variables_drops_none() -> None:
    assert compact_variables(
        {"startDate": "2026-01-01", "processDate": None, "after": "12"}
    ) == {"startDate": "2026-01-01", "after": "12"}


def test_after_cursor_is_json_string_not_number() -> None:
    cursor = "2555157058415855730"
    encoded = json.dumps(compact_variables({"after": cursor}))
    parsed = json.loads(encoded)
    assert parsed["after"] == cursor
    assert isinstance(parsed["after"], str)
    assert f'"{cursor}"' in encoded


def test_auth_header_uses_apikey_scheme() -> None:
    session = FakeSession(
        [FakeResponse(200, {"data": {"models": [{"name": "revenue", "unit": "REVENUE"}]}})]
    )
    client = PrescientClient(
        "https://api.prescient-ai.io/graphql",
        "tok_test",
        session=session,  # type: ignore[arg-type]
    )
    client.probe()
    headers = session.calls[0]["headers"]
    assert headers["Authorization"] == "apikey tok_test"


def test_http_401_is_auth_error() -> None:
    session = FakeSession([FakeResponse(401, {"errors": [{"message": "nope"}]})])
    with pytest.raises(PrescientAuthError, match=AUTH_FAILED_MESSAGE):
        graphql(
            api_url="https://example.test/graphql",
            api_token="bad",
            query=MODELS_QUERY,
            session=session,  # type: ignore[arg-type]
        )


def test_graphql_auth_error_in_200_body() -> None:
    session = FakeSession(
        [FakeResponse(200, {"data": None, "errors": [{"message": AUTH_FAILED_MESSAGE}]})]
    )
    with pytest.raises(PrescientAuthError, match=AUTH_FAILED_MESSAGE):
        graphql(
            api_url="https://example.test/graphql",
            api_token="bad",
            query=MODELS_QUERY,
            session=session,  # type: ignore[arg-type]
        )


def test_retries_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("client.time.sleep", lambda _seconds: None)
    session = FakeSession(
        [
            FakeResponse(429, headers={"Retry-After": "0"}),
            FakeResponse(200, {"data": {"models": []}}),
        ]
    )
    data = graphql(
        api_url="https://example.test/graphql",
        api_token="tok",
        query=MODELS_QUERY,
        session=session,  # type: ignore[arg-type]
    )
    assert data == {"models": []}
    assert len(session.calls) == 2


def test_exhausted_retries_raise_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("client.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("client.MAX_RETRIES", 1)
    session = FakeSession(
        [FakeResponse(503), FakeResponse(503)]
    )
    with pytest.raises(PrescientTransientError):
        graphql(
            api_url="https://example.test/graphql",
            api_token="tok",
            query=MODELS_QUERY,
            session=session,  # type: ignore[arg-type]
        )


def test_http_400_is_not_retryable() -> None:
    session = FakeSession([FakeResponse(400, {"error": "bad request"})])
    with pytest.raises(PrescientApiError, match="HTTP 400"):
        graphql(
            api_url="https://example.test/graphql",
            api_token="tok",
            query=MODELS_QUERY,
            session=session,  # type: ignore[arg-type]
        )
    assert len(session.calls) == 1


def test_graphql_application_error() -> None:
    session = FakeSession(
        [FakeResponse(200, {"data": None, "errors": [{"message": "boom"}]})]
    )
    with pytest.raises(PrescientApiError, match="boom"):
        graphql(
            api_url="https://example.test/graphql",
            api_token="tok",
            query=MODELS_QUERY,
            session=session,  # type: ignore[arg-type]
        )


def test_modeled_metrics_omits_optional_args() -> None:
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "data": {
                        "modeledMetrics": {
                            "data": [],
                            "pageInfo": {"endCursor": None, "hasNextPage": False},
                        }
                    }
                },
            )
        ]
    )
    client = PrescientClient(
        "https://example.test/graphql",
        "tok",
        session=session,  # type: ignore[arg-type]
    )
    client.modeled_metrics(start_date="2026-01-01", end_date="2026-01-31")
    variables = session.calls[0]["json"]["variables"]
    assert variables == {"startDate": "2026-01-01", "endDate": "2026-01-31"}
    assert "after" not in variables
    assert "processDate" not in variables
