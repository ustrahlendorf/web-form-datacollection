"""Init stack that owns static/future SSM Parameter Store configuration.

This stack intentionally does NOT manage the DynamoDB active/passive pointer parameters.
Those are owned/updated by the DynamoDB stack to avoid ownership conflicts during rollover.
"""

from aws_cdk import Stack, aws_ssm as ssm
from constructs import Construct


class InitStack(Stack):
    """Stack responsible for static/future SSM parameters under /HeatingDataCollection/."""

    # Stable, single-environment namespace (no env segment by design)
    SSM_PREFIX = "/HeatingDataCollection"

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment_name: str,
        **kwargs,
    ) -> None:
        """
        Initialize the Init stack.

        Args:
            scope: The parent construct
            construct_id: The logical ID of the stack
            environment_name: The environment name (dev, prod, etc.). Kept for consistency with other stacks.
            **kwargs: Additional arguments to pass to Stack
        """
        super().__init__(scope, construct_id, **kwargs)
        self.environment_name = environment_name

        # Static/future parameters to establish conventions + allow growth without touching infra stacks.
        # NOTE: Values are strings because SSM Parameter Store stores string values and consumers typically
        # treat these as config flags.
        self.schema_version_param = ssm.StringParameter(
            self,
            "ConfigSchemaVersion",
            parameter_name=f"{self.SSM_PREFIX}/Config/SchemaVersion",
            string_value="1",
            description="HeatingDataCollection config schema version (static contract owned by InitStack).",
        )

        self.enable_passive_reads_param = ssm.StringParameter(
            self,
            "FeatureFlagEnablePassiveReads",
            parameter_name=f"{self.SSM_PREFIX}/FeatureFlags/EnablePassiveReads",
            string_value="false",
            description=(
                "Feature flag: when true, API/Lambda may read from passive submissions table "
                "(static contract owned by InitStack)."
            ),
        )

        self.rollover_runbook_version_param = ssm.StringParameter(
            self,
            "OperationsRolloverRunbookVersion",
            parameter_name=f"{self.SSM_PREFIX}/Operations/Rollover/RunbookVersion",
            string_value="2026-01",
            description="Runbook version for annual rollover procedure (static contract owned by InitStack).",
        )


