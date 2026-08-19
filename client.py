"""HTTP client for the Prescient AI GraphQL API.

Auth header is the public contract: `Authorization: apikey <token>`.
See docs/graphql-api.md and https://api.prescient-ai.io/graphql/docs.
"""

from __future__ import annotations

from typing import Any
import logging
import time

import requests

from queries import (
    CHANNEL_NAMES_QUERY,
    MODELED_METRICS_QUERY,
    MODELS_QUERY,
    REPORTED_METRICS_QUERY,
)

log = logging.getLogger("prescient.fivetran")

AUTH_FAILED_MESSAGE = "Authentication failed. Check your token."
DEFAULT_TIMEOUT_SECONDS = 300
MAX_RETRIES = 5
MAX_BACKOFF_SECONDS = 60


class PrescientApiError(RuntimeError):
    """A GraphQL or HTTP failure that should fail the Fivetran sync."""


class PrescientAuthError(PrescientApiError):
    """API token was missing, invalid, expired, or the IP is locked out."""


class PrescientTransientError(PrescientApiError):
    """Retryable network / 5xx / 429 failure after retries are exhausted."""


def _auth_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"apikey {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _is_retryable(exc: BaseException, response: requests.Response | None) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if response is None:
        return False
    return response.status_code == 429 or response.status_code >= 500


def _backoff_seconds(attempt: int, response: requests.Response | None) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), MAX_BACKOFF_SECONDS)
            except ValueError:
                pass
    return min(2**attempt, MAX_BACKOFF_SECONDS)


def graphql(
    *,
    api_url: str,
    api_token: str,
    query: str,
    variables: dict[str, Any] | None = None,
    operation_name: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """POST a GraphQL operation and return the `data` object.

    `after` cursors must already be strings in `variables` so JSON encoding
    never turns a warehouse bigint into a IEEE-754 number.
    """
    payload: dict[str, Any] = {"query": query, "variables": variables or {}}
    if operation_name:
        payload["operationName"] = operation_name

    headers = _auth_headers(api_token)
    http = session or requests
    last_error: BaseException | None = None
    response: requests.Response | None = None

    for attempt in range(MAX_RETRIES + 1):
        response = None
        try:
            response = http.post(
                api_url,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            if response.status_code in (401, 403):
                raise PrescientAuthError(AUTH_FAILED_MESSAGE)
            if response.status_code == 429 or response.status_code >= 500:
                raise requests.HTTPError(
                    f"HTTP {response.status_code}",
                    response=response,
                )
            if response.status_code >= 400:
                raise PrescientApiError(
                    f"Prescient API HTTP {response.status_code}"
                )
            response.raise_for_status()
            body = response.json()
            break
        except PrescientAuthError:
            raise
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
            last_error = exc
            retry_response = getattr(exc, "response", None) or response
            if _is_retryable(exc, retry_response) and attempt < MAX_RETRIES:
                wait = _backoff_seconds(attempt, retry_response)
                log.warning(
                    f"Prescient API call failed (attempt {attempt + 1}/"
                    f"{MAX_RETRIES + 1}): {exc}. Retrying in {wait:.1f}s."
                )
                time.sleep(wait)
                continue
            raise PrescientTransientError(
                f"Prescient API request failed after {attempt + 1} attempts: {exc}"
            ) from exc
        except ValueError as exc:
            raise PrescientApiError(
                "Prescient API returned a non-JSON response."
            ) from exc
    else:
        raise PrescientTransientError(
            f"Prescient API request failed: {last_error}"
        )

    errors = body.get("errors") or []
    if errors:
        messages = "; ".join(
            str(err.get("message") or err) for err in errors if isinstance(err, dict)
        ) or str(errors)
        if AUTH_FAILED_MESSAGE.lower() in messages.lower():
            raise PrescientAuthError(AUTH_FAILED_MESSAGE)
        raise PrescientApiError(f"GraphQL error: {messages}")

    data = body.get("data")
    if not isinstance(data, dict):
        raise PrescientApiError("GraphQL response missing data.")
    return data


def compact_variables(variables: dict[str, Any]) -> dict[str, Any]:
    """Drop None values so optional GraphQL args stay omitted."""
    return {key: value for key, value in variables.items() if value is not None}


class PrescientClient:
    def __init__(
        self,
        api_url: str,
        api_token: str,
        *,
        session: requests.Session | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.api_url = api_url
        self.api_token = api_token
        self.session = session or requests.Session()
        self.timeout = timeout

    def _query(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
    ) -> dict[str, Any]:
        return graphql(
            api_url=self.api_url,
            api_token=self.api_token,
            query=query,
            variables=compact_variables(variables or {}),
            operation_name=operation_name,
            timeout=self.timeout,
            session=self.session,
        )

    def probe(self) -> None:
        """Fail-fast auth check used by setup tests and the start of a sync."""
        self._query(MODELS_QUERY, operation_name="Models")

    def modeled_metrics(
        self,
        *,
        start_date: str,
        end_date: str,
        process_date: str | None = None,
        after: str | None = None,
        sales_channels: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        data = self._query(
            MODELED_METRICS_QUERY,
            {
                "startDate": start_date,
                "endDate": end_date,
                "processDate": process_date,
                "after": after,
                "salesChannel": list(sales_channels) if sales_channels else None,
            },
            operation_name="ModeledMetrics",
        )
        payload = data.get("modeledMetrics")
        if not isinstance(payload, dict):
            raise PrescientApiError("modeledMetrics response was not an object.")
        return payload

    def reported_metrics(
        self,
        *,
        start_date: str,
        end_date: str,
        process_date: str | None = None,
        after: str | None = None,
    ) -> dict[str, Any]:
        data = self._query(
            REPORTED_METRICS_QUERY,
            {
                "startDate": start_date,
                "endDate": end_date,
                "processDate": process_date,
                "after": after,
            },
            operation_name="ReportedMetrics",
        )
        payload = data.get("reportedMetrics")
        if not isinstance(payload, dict):
            raise PrescientApiError("reportedMetrics response was not an object.")
        return payload

    def models(self) -> list[dict[str, Any]]:
        data = self._query(MODELS_QUERY, operation_name="Models")
        rows = data.get("models")
        if not isinstance(rows, list):
            raise PrescientApiError("models response was not a list.")
        return rows

    def channel_names(self) -> list[str]:
        data = self._query(CHANNEL_NAMES_QUERY, operation_name="ChannelNames")
        names = data.get("channelNames")
        if not isinstance(names, list):
            raise PrescientApiError("channelNames response was not a list.")
        return [str(name) for name in names]
