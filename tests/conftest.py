from fivetran_connector_sdk import Logging

# The SDK logger compares LOG_LEVEL to each message level. Unset (None) raises
# TypeError the first time we log, which is what Fivetran production avoids by
# initializing the logger before update() runs.
Logging.LOG_LEVEL = Logging.Level.CRITICAL
