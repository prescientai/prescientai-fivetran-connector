# Prescient AI Fivetran connector

A [Fivetran Connector SDK](https://fivetran.com/docs/connector-sdk) source for the
Prescient AI GraphQL API. Customers deploy it into their own Fivetran destination
and authenticate with a Prescient API token so modeled metrics, reported spend,
models, and channel names land in their warehouse.

## Can clients use this from the Fivetran catalog?

**Not as a native Fivetran connector.** Connector SDK code does not appear under
Add connector in a customer's Fivetran account. Someone has to **deploy the
package into a Fivetran destination**; after that, users only fill in a
Prescient API token on the setup form.

Practical options, cheapest first:

1. **The customer deploys it** into their Fivetran account (`fivetran deploy`,
   below). Their data team needs a Fivetran API key and this repo. This is the
   path the SDK is designed for and does not require Powered by Fivetran.
2. **We deploy it on their behalf** into *their* destination (same CLI / Package
   API, using credentials they grant). They never run Python; they paste the
   token in the connection setup form.
3. **Powered by Fivetran + Connect Cards** — we upload the package per
   connection and send the customer a Connect Card to enter the token. That
   lands data in a destination group we control (or one they already have in
   that PBF account). Requires a PBF contract; it is not the same as the
   catalog listing.
4. **Community Connectors catalog** is a template repo, not a one-click
   install. Fivetran's Partner-Built program (native catalog badge) is
   [not accepting new partners](https://fivetran.com/docs/connectors/partner-built-program).

Each Fivetran package is bound to a single connection, so every customer
connection is a new upload of the same ZIP even when we operate option 2 or 3.

## What it syncs

| Destination table | GraphQL query | Grain / primary key | Sync |
| --- | --- | --- | --- |
| `modeled_metrics` | `modeledMetrics` | campaign, source channel, reported date, metric, model target, target channel | Incremental via `processDate` |
| `reported_metrics` | `reportedMetrics` | campaign, channel, reported date | Incremental via `processDate` |
| `models` | `models` | `name` | Full refresh each sync |
| `channel_names` | `channelNames` | `name` | Full refresh each sync |

The public API is read-only, token-authenticated, and documented at
`https://api.prescientai.com/graphql/docs`. Auth header:

```
Authorization: apikey <YOUR_TOKEN>
```

Generate a token in the Prescient dashboard: **Settings → API**. Tokens can be
scoped to a subset of channels; the connector inherits that scope — it does not
widen access.

### Incremental sync

`modeledMetrics` and `reportedMetrics` both accept `processDate`, which the API
docs recommend using so clients skip unchanged history. After each successful
table sync the connector stores today's UTC date in Fivetran state and sends it
as `processDate` on the next run. `startDate` stays at the configured historical
bound so a reprocessed older `reported_date` is still returned.

Pagination follows the API contract:

- `modeledMetrics` — keyset cursor (`after` is a `BigInt` **string**; warehouse
  ids exceed JavaScript's safe integer range)
- `reportedMetrics` — offset cursor (`after` is the previous `endCursor`)
- Page size is server-capped at 5,000 rows

Progress is checkpointed after every page so a failed long sync resumes mid-way
instead of restarting the table.

If `start_date` or `sales_channel` changes after a connection has already
synced, the connector treats that as a new scope: it truncates the metric table
(soft-delete) and re-runs a full historical pull so newly included rows are not
skipped and newly excluded rows do not linger.

`models` and `channel_names` are small dimension tables. Each sync truncates
them (soft-delete) and upserts the current set so removals show up as
`_fivetran_deleted`.

## Configuration

All values are strings — that is a Connector SDK requirement.

| Key | Required | Default | Description |
| --- | --- | --- | --- |
| `api_token` | yes | — | Prescient API token |
| `api_url` | no | `https://api.prescientai.com/graphql` | GraphQL endpoint. Must be `https://` ( `http://` is allowed only for localhost). A host without `/graphql` is accepted. |
| `start_date` | no | `2018-01-01` | Inclusive `reported_date` lower bound (`YYYY-MM-DD`) |
| `sales_channel` | no | `all` | `all`, `ECOMMERCE`, or `RETAIL`. Applies to modeled metrics only. |
| `sync_modeled_metrics` | no | `true` | Set `false` to skip the table |
| `sync_reported_metrics` | no | `true` | Set `false` to skip the table |
| `sync_models` | no | `true` | Set `false` to skip the table |
| `sync_channel_names` | no | `true` | Set `false` to skip the table |

A dashboard setup form (`configuration_form`) collects the same fields when the
connection is created in Fivetran, and runs a `models` probe as a connection
test.

Copy `configuration.json.example` to `configuration.json` for local runs.
**Never commit `configuration.json`.** Fivetran encrypts these values after
deploy; delete the local file once the connection exists.

## Local development

Package manager is [uv](https://docs.astral.sh/uv/). Fivetran itself accepts
either `pyproject.toml` or `requirements.txt`; this project uses `pyproject.toml`
because that is what uv manages, and Fivetran prefers `pyproject.toml` when both
are present.

Runtime `dependencies` in `pyproject.toml` are **empty on purpose**. The
Connector SDK runtime already ships `fivetran_connector_sdk` and `requests`.
Declaring them as project dependencies can conflict with the managed versions.
See [Project Dependencies](https://fivetran.com/docs/connector-sdk/connector-development-and-configuration/project-dependencies).

```bash
uv sync
uv run pytest
```

Install the Fivetran CLI via the SDK (already in the `dev` dependency group):

```bash
uv run fivetran debug --configuration configuration.json
```

`fivetran debug` writes a local DuckDB warehouse at `files/warehouse.db`. Inspect
it with the DuckDB CLI or DBeaver.

Python 3.10–3.14 are supported by Fivetran. Local pin is 3.12 (`.python-version`).

## Deploy to Fivetran

Prerequisites: a Fivetran account, a destination, and a scoped API key. See the
[setup guide](https://fivetran.com/docs/connectors/connector-sdk/setup-guide).

```bash
cp configuration.json.example configuration.json
# fill in api_token (and any overrides)

uv run fivetran deploy \
  --api-key <BASE_64_ENCODED_API_KEY> \
  --destination <DESTINATION_NAME> \
  --connection prescient_ai \
  --configuration configuration.json \
  --python 3.12
```

Connection names must be lowercase (`a-z`, digits, `_`). The new connection is
paused; unpause it in the dashboard to start the historical sync.

Redeploy with the same destination and connection name to ship code changes.
Omit `--configuration` on a redeploy to keep the token already stored in
Fivetran.

Each customer needs their own connection (their token, their destination). The
same `connector.py` can be deployed many times with different
`configuration.json` files / connection names.

## Layout

```
connector.py   Fivetran entry: schema(), update(), configuration_form()
client.py      GraphQL HTTP client (retries, auth errors)
queries.py     GraphQL documents
config.py      configuration.json parsing
mapping.py     GraphQL row → destination column mapping
sync.py        pagination, processDate state, truncates
tests/         pytest (no Fivetran runtime required)
```

Supporting modules are imported by `connector.py`. That is the Connector SDK
[multiple-file pattern](https://fivetran.com/docs/connectors/connector-sdk/setup-guide).
