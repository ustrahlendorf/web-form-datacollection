"""DynamoDB stack for data persistence."""

from aws_cdk import (
    Stack,
    aws_dynamodb as dynamodb,
    aws_ssm as ssm,
    CfnOutput,
    RemovalPolicy,
)
from constructs import Construct


class DynamoDBStack(Stack):
    """Stack for DynamoDB table and data persistence configuration."""

    SSM_PREFIX = "/HeatingDataCollection"

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment_name: str,
        active_submissions_table_name: str,
        passive_submissions_table_name: str,
        **kwargs
    ) -> None:
        """
        Initialize the DynamoDB stack.

        Args:
            scope: The parent construct
            construct_id: The logical ID of the stack
            environment_name: The environment name (dev, prod, etc.)
            active_submissions_table_name: Physical table name for the active (current) submissions table
            passive_submissions_table_name: Physical table name for the passive (previous) submissions table
            **kwargs: Additional arguments to pass to Stack
        """
        super().__init__(scope, construct_id, **kwargs)
        self.environment_name = environment_name

        if not active_submissions_table_name:
            raise ValueError("active_submissions_table_name must not be empty")
        if not passive_submissions_table_name:
            raise ValueError("passive_submissions_table_name must not be empty")
        if active_submissions_table_name == passive_submissions_table_name:
            raise ValueError(
                "active_submissions_table_name and passive_submissions_table_name must be different"
            )

        # IMPORTANT:
        # - We create BOTH physical tables from the two provided names.
        # - We assign the names to construct IDs in a stable way (sorted order) so swapping
        #   ACTIVE/PASSIVE env vars does NOT trigger CloudFormation table replacements.
        # - The *role* (active vs passive) is expressed only via exports and API wiring.
        table_name_a, table_name_b = sorted(
            [str(active_submissions_table_name), str(passive_submissions_table_name)]
        )

        # Create DynamoDB table for active submissions.
        # We keep the construct IDs stable to avoid CloudFormation resource replacement.
        submissions_2025_table = dynamodb.Table(
            self,
            "Submissions2025Table",
            table_name=table_name_a,
            partition_key=dynamodb.Attribute(
                name="user_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp_utc",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            # Keep historical data unless explicitly removed out-of-band.
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery=True,
        )

        # Store reference for use by other stacks
        self.submissions_2025_table = submissions_2025_table

        # Create DynamoDB table for passive submissions (previous year / roll-over source).
        # We keep the construct IDs stable to avoid CloudFormation resource replacement.
        submissions_2026_table = dynamodb.Table(
            self,
            "Submissions2026Table",
            table_name=table_name_b,
            partition_key=dynamodb.Attribute(
                name="user_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp_utc",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            # Keep historical data unless explicitly removed out-of-band.
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery=True,
        )

        # Store reference for use by other stacks (future roll-over)
        self.submissions_2026_table = submissions_2026_table

        # IMPORTANT:
        # CDK's `table.table_name` is commonly a Token at synth-time (even if `table_name=` is set),
        # so using it as a dict key and then looking up via the raw env var string can fail.
        # We instead key by the *known input strings* to keep selection deterministic at runtime.
        tables_by_name = {
            table_name_a: submissions_2025_table,
            table_name_b: submissions_2026_table,
        }
        try:
            active_table = tables_by_name[active_submissions_table_name]
            passive_table = tables_by_name[passive_submissions_table_name]
        except KeyError as exc:
            raise KeyError(
                "Provided table name was not one of the two tables created in this stack. "
                f"active_submissions_table_name={active_submissions_table_name!r}, "
                f"passive_submissions_table_name={passive_submissions_table_name!r}, "
                f"created={[table_name_a, table_name_b]!r}"
            ) from exc

        # ---------------------------------------------------------------------
        # SSM Parameter Store pointers (single-environment namespace)
        #
        # These parameters provide a stable indirection layer for the "active vs passive"
        # submissions table pointers, avoiding brittle CloudFormation Export/Import coupling.
        #
        # Ownership: DynamoDBStack (these values change during annual rollover)
        # ---------------------------------------------------------------------
        self.submissions_active_table_name_pointer = ssm.StringParameter(
            self,
            "SubmissionsActiveTableNamePointer",
            parameter_name=f"{self.SSM_PREFIX}/Submissions/Active/TableName",
            string_value=active_table.table_name,
            description="Pointer: active (current) DynamoDB submissions table name",
        )
        self.submissions_active_table_arn_pointer = ssm.StringParameter(
            self,
            "SubmissionsActiveTableArnPointer",
            parameter_name=f"{self.SSM_PREFIX}/Submissions/Active/TableArn",
            string_value=active_table.table_arn,
            description="Pointer: active (current) DynamoDB submissions table ARN",
        )
        self.submissions_passive_table_name_pointer = ssm.StringParameter(
            self,
            "SubmissionsPassiveTableNamePointer",
            parameter_name=f"{self.SSM_PREFIX}/Submissions/Passive/TableName",
            string_value=passive_table.table_name,
            description="Pointer: passive (previous) DynamoDB submissions table name",
        )
        self.submissions_passive_table_arn_pointer = ssm.StringParameter(
            self,
            "SubmissionsPassiveTableArnPointer",
            parameter_name=f"{self.SSM_PREFIX}/Submissions/Passive/TableArn",
            string_value=passive_table.table_arn,
            description="Pointer: passive (previous) DynamoDB submissions table ARN",
        )

        # ---------------------------------------------------------------------
        # Backward-compatible (LEGACY) exports
        #
        # Older deployed stacks (e.g. DataCollectionAPI-dev) may still import:
        # - DataCollectionSubmissionsTableName2025-<env>
        # - DataCollectionSubmissionsTableArn2025-<env>
        #
        # CloudFormation blocks deleting an Export that is in-use by another stack,
        # which can put this stack into UPDATE_ROLLBACK_COMPLETE.
        #
        # We keep these legacy exports temporarily and point them to the *active* table
        # (the semantics the old "2025" export effectively had: "current submissions table").
        # Once all stacks have migrated to the new Active/Passive exports, these can be removed.
        # ---------------------------------------------------------------------
        CfnOutput(
            self,
            "LegacySubmissionsTableName2025",
            value=active_table.table_name,
            export_name=f"DataCollectionSubmissionsTableName2025-{environment_name}",
            description="LEGACY (temporary): kept for stacks importing the old 2025 table name export",
        )

        CfnOutput(
            self,
            "LegacySubmissionsTableArn2025",
            value=active_table.table_arn,
            export_name=f"DataCollectionSubmissionsTableArn2025-{environment_name}",
            description="LEGACY (temporary): kept for stacks importing the old 2025 table ARN export",
        )

        # Export active table name/ARN (scoped by env to avoid export collisions)
        CfnOutput(
            self,
            "SubmissionsActiveTableName",
            value=active_table.table_name,
            export_name=f"DataCollectionSubmissionsActiveTableName-{environment_name}",
            description="DynamoDB submissions active table name",
        )

        CfnOutput(
            self,
            "SubmissionsActiveTableArn",
            value=active_table.table_arn,
            export_name=f"DataCollectionSubmissionsActiveTableArn-{environment_name}",
            description="DynamoDB submissions active table ARN",
        )

        # Export passive table name/ARN (scoped by env to avoid export collisions)
        CfnOutput(
            self,
            "SubmissionsPassiveTableName",
            value=passive_table.table_name,
            export_name=f"DataCollectionSubmissionsPassiveTableName-{environment_name}",
            description="DynamoDB submissions passive table name",
        )

        CfnOutput(
            self,
            "SubmissionsPassiveTableArn",
            value=passive_table.table_arn,
            export_name=f"DataCollectionSubmissionsPassiveTableArn-{environment_name}",
            description="DynamoDB submissions passive table ARN",
        )
