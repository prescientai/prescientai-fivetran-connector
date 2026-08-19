# Prescient AI Fivetran connector

Load Prescient modeled metrics, reported spend, models, and channel names into
your warehouse with [Fivetran](https://www.fivetran.com/).

This is a [Fivetran Connector SDK](https://fivetran.com/docs/connector-sdk)
package, not a native listing in the Fivetran catalog. You deploy it into your
Fivetran destination once; after that, Fivetran runs it on a schedule and you
only need a Prescient API token.

## Prerequisites

- A Fivetran account with a destination already set up
- A Fivetran API key ([how to create one](https://fivetran.com/docs/rest-api/getting-started))
- A Prescient API token (Prescient dashboard → **Settings → API**)
- Python 3.10–3.14 and [uv](https://docs.astral.sh/uv/)

Tokens can be scoped to a subset of channels. The connector inherits that
scope; it does not widen access.

## Deploy into your Fivetran account

```bash
git clone https://github.com/prescientai/prescientai-fivetran-connector.git
cd prescientai-fivetran-connector

uv sync
cp configuration.json.example configuration.json
```

Edit `configuration.json` and set `api_token` to your Prescient API token.
Leave the other keys unless you want to change the historical start date,
sales channel, or skip a table.

`--api-key` is **not** the raw Fivetran key. It is the base64 encoding of
`{api_key}:{api_secret}` (Fivetran shows both when you create the key):

```bash
export FIVETRAN_API_KEY="$(printf '%s' 'YOUR_KEY:YOUR_SECRET' | base64)"
```

The CLI lives in the project virtualenv. `uv pip install` is not enough — run
it with `uv run` (or `source .venv/bin/activate` first):

```bash
uv run fivetran deploy \
  --api-key "$FIVETRAN_API_KEY" \
  --destination Snowflake \
  --connection prescient_ai \
  --configuration configuration.json \
  --python 3.12
```

`--destination` is the exact name from the Fivetran Destinations page (case
matters; `Snowflake` is valid). `--connection` is a name you choose and must
be lowercase (`a-z`, digits, `_`). The new connection is **paused** after
deploy — open it in the Fivetran dashboard and unpause it to start the
historical sync.

Do not commit `configuration.json`. Fivetran encrypts the values after deploy;
you can delete the local file once the connection exists.

### Update an existing connection

Redeploy with the same destination and connection name to pick up connector
updates. Omit `--configuration` to keep the token already stored in Fivetran:

```bash
git pull
uv run fivetran deploy \
  --api-key "$FIVETRAN_API_KEY" \
  --destination Snowflake \
  --connection prescient_ai \
  --python 3.12
```

Each Fivetran destination needs its own connection (your token, your warehouse).

## What lands in your warehouse

| Table | Source | Grain | Sync |
| --- | --- | --- | --- |
| `modeled_metrics` | `modeledMetrics` | campaign, source channel, reported date, metric, model target, target channel | Incremental via `processDate` |
| `reported_metrics` | `reportedMetrics` | campaign, channel, reported date | Incremental via `processDate` |
| `models` | `models` | `name` | Full refresh each sync |
| `channel_names` | `channelNames` | `name` | Full refresh each sync |

The API is read-only. Schema and query docs: https://api.prescient-ai.io/graphql/docs

Auth header if you call the API yourself:

```
Authorization: apikey <YOUR_TOKEN>
```

### Incremental sync

After each successful metric-table sync, the connector stores today’s UTC date
and sends it as `processDate` on the next run. `start_date` stays at the
configured historical bound, so a reprocessed older `reported_date` is still
returned.

Pagination:

- `modeledMetrics` — keyset cursor (`after` is a `BigInt` string)
- `reportedMetrics` — offset cursor (`after` is the previous `endCursor`)
- Page size is server-capped at 5,000 rows

Progress is checkpointed after every page so a failed long sync resumes instead
of restarting the table.

If you change `start_date` or `sales_channel` after a connection has already
synced, the connector treats that as a new scope: it truncates the metric table
(soft-delete) and re-runs a full historical pull.

`models` and `channel_names` are small dimension tables. Each sync truncates
them (soft-delete) and upserts the current set so removals show up as
`_fivetran_deleted`.

## Configuration

All values are strings — that is a Connector SDK requirement. The same fields
appear on the Fivetran setup form when you create the connection. A connection
test probes the `models` query with your token.

| Key | Required | Default | Description |
| --- | --- | --- | --- |
| `api_token` | yes | — | Prescient API token |
| `api_url` | no | `https://api.prescient-ai.io/graphql` | GraphQL endpoint. Must be `https://` (`http://` is allowed only for localhost). A host without `/graphql` is accepted. |
| `start_date` | no | `2018-01-01` | Inclusive `reported_date` lower bound (`YYYY-MM-DD`) |
| `sales_channel` | no | `all` | `all`, `ECOMMERCE`, or `RETAIL`. Applies to modeled metrics only. |
| `sync_modeled_metrics` | no | `true` | Set `false` to skip the table |
| `sync_reported_metrics` | no | `true` | Set `false` to skip the table |
| `sync_models` | no | `true` | Set `false` to skip the table |
| `sync_channel_names` | no | `true` | Set `false` to skip the table |

## Test locally (optional)

This uses [uv](https://docs.astral.sh/uv/) and the Connector SDK tester. It
writes a local DuckDB warehouse at `files/warehouse.db`.

```bash
uv sync
uv run pytest

cp configuration.json.example configuration.json
# fill in api_token

uv run fivetran debug --configuration configuration.json
```

Runtime `dependencies` in `pyproject.toml` are empty on purpose. Fivetran
already ships `fivetran_connector_sdk` and `requests`; declaring them as
project dependencies can conflict with the managed versions. See
[Project Dependencies](https://fivetran.com/docs/connector-sdk/connector-development-and-configuration/project-dependencies).

Python 3.10–3.14 are supported by Fivetran. Local pin is 3.12 (`.python-version`).

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

## Support

Questions about your Prescient data or API token: contact your Prescient
representative, or generate a token in the dashboard under **Settings → API**.

Connector bugs and pull requests: open an issue on this repository.
`main` is protected — changes go through pull requests and must pass tests.
