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

        # Create DynamoDB table for submissions
        submissions_table = dynamodb.Table(
            self,
            "SubmissionsTable",
            table_name=f"submissions-{environment_name}",
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
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery=True,
        )

        # Store reference for use by other stacks
        self.submissions_table = submissions_table

        # Export table name for Lambda functions
        CfnOutput(
            self,
            "SubmissionsTableName",
            value=submissions_table.table_name,
            export_name=f"DataCollectionSubmissionsTableName-{environment_name}",
            description="DynamoDB submissions table name",
        )

        # Export table ARN for IAM policies
        CfnOutput(
            self,
            "SubmissionsTableArn",
            value=submissions_table.table_arn,
            export_name=f"DataCollectionSubmissionsTableArn-{environment_name}",
            description="DynamoDB submissions table ARN",
        )
