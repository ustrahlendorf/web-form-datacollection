"""DynamoDB stack for data persistence."""

from aws_cdk import (
    Stack,
    aws_dynamodb as dynamodb,
    CfnOutput,
    RemovalPolicy,
)
from constructs import Construct


class DynamoDBStack(Stack):
    """Stack for DynamoDB table and data persistence configuration."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment_name: str,
        **kwargs
    ) -> None:
        """
        Initialize the DynamoDB stack.

        Args:
            scope: The parent construct
            construct_id: The logical ID of the stack
            environment_name: The environment name (dev, prod, etc.)
            **kwargs: Additional arguments to pass to Stack
        """
        super().__init__(scope, construct_id, **kwargs)
        self.environment_name = environment_name

        # Create DynamoDB table for historical submissions import (fixed name).
        # This is intentionally NOT environment-suffixed because the requirement is a
        # specific table name: submissions-2025.
        submissions_2025_table = dynamodb.Table(
            self,
            "Submissions2025Table",
            table_name="submissions-2025",
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

        # Export 2025 table name/ARN for IAM policies and tooling (scoped by env to avoid export collisions)
        CfnOutput(
            self,
            "Submissions2025TableName",
            value=submissions_2025_table.table_name,
            export_name=f"DataCollectionSubmissionsTableName2025-{environment_name}",
            description="DynamoDB submissions-2025 table name",
        )

        CfnOutput(
            self,
            "Submissions2025TableArn",
            value=submissions_2025_table.table_arn,
            export_name=f"DataCollectionSubmissionsTableArn2025-{environment_name}",
            description="DynamoDB submissions-2025 table ARN",
        )

        # Add next-year table ahead of roll-over.
        # This is also intentionally NOT environment-suffixed because the requirement is a
        # specific table name: submissions-2026.
        #
        # IMPORTANT: This change is non-impacting to the running app as long as the API stack
        # continues to import the 2025 table exports. The 2026 table is created and exported
        # ahead of time so the roll-over can be performed as a separate (small) change.
        submissions_2026_table = dynamodb.Table(
            self,
            "Submissions2026Table",
            table_name="submissions-2026",
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

        # Export 2026 table name/ARN for future IAM policies and tooling (scoped by env to avoid export collisions)
        CfnOutput(
            self,
            "Submissions2026TableName",
            value=submissions_2026_table.table_name,
            export_name=f"DataCollectionSubmissionsTableName2026-{environment_name}",
            description="DynamoDB submissions-2026 table name",
        )

        CfnOutput(
            self,
            "Submissions2026TableArn",
            value=submissions_2026_table.table_arn,
            export_name=f"DataCollectionSubmissionsTableArn2026-{environment_name}",
            description="DynamoDB submissions-2026 table ARN",
        )
