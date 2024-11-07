"""Sentry SDK configuration"""

import sentry_sdk
from sentry_sdk.integrations.grpc import GRPCIntegration

from utils import get_configs

SENTRY_ENABLED = bool(get_configs("SENTRY_DSN"))


def initialize_sentry():
    """
    Initializes Sentry SDK.
    """

    sentry_sdk.init(
        dsn=get_configs("SENTRY_DSN"),
        server_name="Publisher",
        traces_sample_rate=float(
            get_configs("SENTRY_TRACES_SAMPLE_RATE", default_value=1.0)
        ),
        profiles_sample_rate=float(
            get_configs("SENTRY_PROFILES_SAMPLE_RATE", default_value=1.0)
        ),
        integrations=[GRPCIntegration()],
    )

    sentry_sdk.set_tag("project", "Publisher")
    sentry_sdk.set_tag("service_name", "Publisher Service")
