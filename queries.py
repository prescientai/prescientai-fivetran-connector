"""GraphQL documents for the Prescient AI public API.

The schema is a frozen contract. Field names, pagination, and argument types
must stay aligned with `app/api/graphql/schema.graphql` in the platform repo
(and https://api.prescient-ai.io/graphql/docs).

`after` is a GraphQL `BigInt` encoded as a decimal *string*. Modeled-metric
cursors are warehouse ids that exceed JavaScript's safe integer range, so the
JSON body must quote them. Never coerce them to `int` before sending.

Do not call the unpaginated `models` field. It runs `DISTINCT target` over
`ml_attribution_run_outputs` with no date window and hits the warehouse
statement timeout. The `models` destination table is derived from paginated
`modeledMetrics.target` instead. `channelNames` hits the same table but
`DISTINCT source_channel_name` (tiny cardinality) and is safe to call.
Setup tests use a one-day `modeledMetrics` window so they stay inside the
timeout.
"""

MODELED_METRICS_QUERY = """
query ModeledMetrics(
  $startDate: ISO8601Date
  $endDate: ISO8601Date
  $processDate: ISO8601Date
  $after: BigInt
  $salesChannel: [SalesChannelEnum!]
) {
  modeledMetrics(
    startDate: $startDate
    endDate: $endDate
    processDate: $processDate
    after: $after
    salesChannel: $salesChannel
  ) {
    data {
      metricName
      metricValue
      processDate
      reportedDate
      sourceCampaignId
      sourceCampaignName
      sourceChannelName
      target
      targetChannelName
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
""".strip()

REPORTED_METRICS_QUERY = """
query ReportedMetrics(
  $startDate: ISO8601Date
  $endDate: ISO8601Date
  $processDate: ISO8601Date
  $after: BigInt
) {
  reportedMetrics(
    startDate: $startDate
    endDate: $endDate
    processDate: $processDate
    after: $after
  ) {
    data {
      campaignId
      campaignName
      channelName
      processDate
      reportedDate
      spend
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
""".strip()

# Auth + reachability only. Date-bounded so the warehouse uses the paginated
# modeledMetrics path (LIMIT 5000 + reported_date + process_date) instead of
# the unpaginated models DISTINCT. Selecting pageInfo still executes the page
# query server-side; the window keeps it cheap.
CONNECTION_PROBE_QUERY = """
query ConnectionProbe(
  $startDate: ISO8601Date
  $endDate: ISO8601Date
  $processDate: ISO8601Date
) {
  modeledMetrics(
    startDate: $startDate
    endDate: $endDate
    processDate: $processDate
  ) {
    pageInfo {
      hasNextPage
    }
  }
}
""".strip()

CHANNEL_NAMES_QUERY = """
query ChannelNames {
  channelNames
}
""".strip()
