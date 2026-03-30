"""Init stack that owns static/future SSM Parameter Store configuration.

This stack intentionally does NOT manage the DynamoDB active/passive pointer parameters.
Those are owned/updated by the DynamoDB stack to avoid ownership conflicts during rollover.
"""

from aws_cdk import Stack, aws_ssm as ssm
from constructs import Construct

from infrastructure.stacks.ssm_contract import (
    DEFAULT_SSM_NAMESPACE_PREFIX,
    normalize_namespace_prefix,
    ssm_parameter_name,
)


class InitStack(Stack):
    """Stack responsible for static/future SSM parameters under a configured namespace."""

    DEFAULT_SSM_PREFIX = DEFAULT_SSM_NAMESPACE_PREFIX

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment_name: str,
        ssm_namespace_prefix: str = DEFAULT_SSM_PREFIX,
        **kwargs,
    ) -> None:
        """
        Initialize the Init stack.

        Args:
            scope: The parent construct
            construct_id: The logical ID of the stack
            environment_name: The environment name (dev, prod, etc.). Kept for consistency with other stacks.
            ssm_namespace_prefix: Root SSM namespace prefix (for example /HeatingDataCollection)
            **kwargs: Additional arguments to pass to Stack
        """
        super().__init__(scope, construct_id, **kwargs)
        self.environment_name = environment_name
        self.ssm_prefix = normalize_namespace_prefix(ssm_namespace_prefix)

        def _param_name(*segments: str) -> str:
            return ssm_parameter_name(self.ssm_prefix, *segments)

        # Static/future parameters to establish conventions + allow growth without touching infra stacks.
        # NOTE: Values are strings because SSM Parameter Store stores string values and consumers typically
        # treat these as config flags.
        self.schema_version_param = ssm.StringParameter(
            self,
            "ConfigSchemaVersion",
            parameter_name=_param_name("Config", "SchemaVersion"),
            string_value="1",
            description="HeatingDataCollection config schema version (static contract owned by InitStack).",
        )

        self.enable_passive_reads_param = ssm.StringParameter(
            self,
            "FeatureFlagEnablePassiveReads",
            parameter_name=_param_name("FeatureFlags", "EnablePassiveReads"),
            string_value="false",
            description=(
                "Feature flag: when true, API/Lambda may read from passive submissions table "
                "(static contract owned by InitStack)."
            ),
        )

        self.rollover_runbook_version_param = ssm.StringParameter(
            self,
            "OperationsRolloverRunbookVersion",
            parameter_name=_param_name("Operations", "Rollover", "RunbookVersion"),
            string_value="2026-01",
            description="Runbook version for annual rollover procedure (static contract owned by InitStack).",
        )

        # Auto-retrieval parameters (Viessmann API → DynamoDB, scheduled daily)
        self.auto_retrieval_schedule_param = ssm.StringParameter(
            self,
            "AutoRetrievalScheduleCron",
            parameter_name=_param_name("AutoRetrieval", "ScheduleCron"),
            string_value="0 7 * * ? *",
            description=(
                "EventBridge Scheduler cron fields for daily retrieval (minutes hours day-of-month month "
                "day-of-week year), evaluated in ScheduleTimezone (default: 07:00 local wall time)."
            ),
        )

        self.auto_retrieval_schedule_timezone_param = ssm.StringParameter(
            self,
            "AutoRetrievalScheduleTimezone",
            parameter_name=_param_name("AutoRetrieval", "ScheduleTimezone"),
            string_value="Europe/Berlin",
            description=(
                "IANA timezone for daily ScheduleCron (EventBridge Scheduler). "
                "DST transitions apply automatically (static contract owned by InitStack)."
            ),
        )

        self.auto_retrieval_frequent_schedule_param = ssm.StringParameter(
            self,
            "AutoRetrievalFrequentScheduleCron",
            parameter_name=_param_name("AutoRetrieval", "FrequentScheduleCron"),
            string_value="0/15 * * * ? *",
            description="EventBridge cron for frequent scheduler (every 15 minutes within active windows).",
        )

        # Migration-only runtime fallback parameters.
        # Runtime source of truth has moved to AppConfig; these remain temporarily for safe cutover.
        self.auto_retrieval_frequent_active_windows_param = ssm.StringParameter(
            self,
            "AutoRetrievalFrequentActiveWindows",
            parameter_name=_param_name("AutoRetrieval", "FrequentActiveWindows"),
            string_value='[{"start":"00:00","stop":"24:00"}]',
            description=(
                "Active time windows for frequent scheduler (JSON array of {start,stop} in UTC HH:MM). "
                "Migration-only SSM fallback while AppConfig rollout completes. "
                "Lambda exits early if invoked outside any window. Default: 24/7. Max 5 windows."
            ),
        )

        self.auto_retrieval_max_retries_param = ssm.StringParameter(
            self,
            "AutoRetrievalMaxRetries",
            parameter_name=_param_name("AutoRetrieval", "MaxRetries"),
            string_value="5",
            description="Migration-only SSM fallback for max retry attempts (runtime source is AppConfig).",
        )

        self.auto_retrieval_retry_delay_param = ssm.StringParameter(
            self,
            "AutoRetrievalRetryDelaySeconds",
            parameter_name=_param_name("AutoRetrieval", "RetryDelaySeconds"),
            string_value="300",
            description="Migration-only SSM fallback for retry delay seconds (runtime source is AppConfig).",
        )

        self.auto_retrieval_user_id_param = ssm.StringParameter(
            self,
            "AutoRetrievalUserId",
            parameter_name=_param_name("AutoRetrieval", "UserId"),
            string_value="SET_ME",
            description=(
                "Migration-only SSM fallback for installation owner user_id (runtime source is AppConfig). "
                "Update only during cutover troubleshooting."
            ),
        )


