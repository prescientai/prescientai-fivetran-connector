"""GraphQL documents for the Prescient AI public API.

The schema is a frozen contract. Field names, pagination, and argument types
must stay aligned with `app/api/graphql/schema.graphql` in the platform repo
(and https://api.prescientai.com/graphql/docs).

`after` is a GraphQL `BigInt` encoded as a decimal *string*. Modeled-metric
cursors are warehouse ids that exceed JavaScript's safe integer range, so the
JSON body must quote them. Never coerce them to `int` before sending.
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

MODELS_QUERY = """
query Models {
  models {
    name
    unit
  }
}
""".strip()

CHANNEL_NAMES_QUERY = """
query ChannelNames {
  channelNames
}
""".strip()
