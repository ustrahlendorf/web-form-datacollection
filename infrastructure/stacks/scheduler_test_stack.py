"""Scheduler test stack for safe end-to-end auto-retrieval testing.

Creates an isolated test DynamoDB table and Lambda (same handler as production)
pointing to the test table. EventBridge Rule triggers multiple runs per day for validation.
Uses a separate SNS topic for failure alerts to avoid spurious production notifications.
"""

from aws_cdk import (
    BundlingOptions,
    Stack,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_sns as sns,
    aws_ssm as ssm,
    CfnOutput,
    Duration,
    RemovalPolicy,
)
from constructs import Construct
import os


class SchedulerTestStack(Stack):
    """Stack for testing auto-retrieval Lambda with isolated DynamoDB table and SNS topic."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment_name: str,
        viessmann_credentials_secret_arn: str,
        **kwargs,
    ) -> None:
        """
        Initialize the Scheduler test stack.

        Args:
            scope: The parent construct
            construct_id: The logical ID of the stack
            environment_name: The environment name (dev, prod, etc.)
            viessmann_credentials_secret_arn: ARN of Secrets Manager secret with
                VIESSMANN_CLIENT_ID, VIESSMANN_EMAIL, VIESSMANN_PASSWORD
            **kwargs: Additional arguments to pass to Stack
        """
        super().__init__(scope, construct_id, **kwargs)
        self.environment_name = environment_name

        # Read test schedule from SSM (parameter created by InitStack)
        test_schedule_cron = ssm.StringParameter.value_for_string_parameter(
            self, "/HeatingDataCollection/AutoRetrieval/TestScheduleCron"
        )

        # Test DynamoDB table — same schema as production (user_id, timestamp_utc)
        test_table = dynamodb.Table(
            self,
            "SubmissionsAutoRetrievalTestTable",
            table_name=f"submissions-auto-retrieval-test-{environment_name}",
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
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Separate test SNS topic — avoids spurious production alerts
        test_failure_topic = sns.Topic(
            self,
            "AutoRetrievalTestFailureTopic",
            display_name="Auto-retrieval test failure alerts",
            topic_name=f"heating-auto-retrieval-test-failure-{environment_name}",
        )

        # Lambda execution role — access only to test table and test SNS
        lambda_role = iam.Role(
            self,
            "AutoRetrievalTestLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            role_name=f"heating-auto-retrieval-test-role-{environment_name}",
        )

        lambda_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaBasicExecutionRole"
            )
        )

        lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["secretsmanager:GetSecretValue"],
                resources=[viessmann_credentials_secret_arn],
            )
        )

        lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/HeatingDataCollection/AutoRetrieval/*"
                ],
            )
        )

        lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:PutItem",
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                ],
                resources=[test_table.table_arn],
            )
        )

        lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["sns:Publish"],
                resources=[test_failure_topic.topic_arn],
            )
        )

        # Lambda function — same handler/code as production
        asset_path = os.path.join(os.path.dirname(__file__), "..", "..")
        pythonpath = "backend/src"

        auto_retrieval_test_fn = lambda_.Function(
            self,
            "AutoRetrievalTestHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="src.handlers.auto_retrieval_handler.lambda_handler",
            code=lambda_.Code.from_asset(
                asset_path,
                exclude=[
                    "cdk.out",
                    ".git",
                    ".venv",
                    "node_modules",
                    ".pytest_cache",
                    ".hypothesis",
                    ".jsii-package-cache",
                ],
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r /asset-input/requirements-heating.txt -t /asset-output "
                        "&& cp -r /asset-input/src /asset-input/backend /asset-output/",
                    ],
                ),
            ),
            role=lambda_role,
            environment={
                "SUBMISSIONS_TABLE": test_table.table_name,
                "VIESSMANN_CREDENTIALS_SECRET_ARN": viessmann_credentials_secret_arn,
                "AUTO_RETRIEVAL_FAILURE_TOPIC_ARN": test_failure_topic.topic_arn,
                "AUTO_RETRIEVAL_SSM_PREFIX": "/HeatingDataCollection/AutoRetrieval",
                "AUTO_RETRIEVAL_SKIP_DUPLICATE": "false",
                "PYTHONPATH": pythonpath,
                "VIESSMANN_TOKEN_CACHE_PATH": "/tmp/viessmann/tokens.json",
            },
            timeout=Duration.minutes(15),
            memory_size=256,
            description="Test Lambda for Viessmann auto-retrieval (writes to test table only)",
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        # EventBridge Rule — triggers test Lambda on schedule (multiple runs per day)
        rule = events.Rule(
            self,
            "AutoRetrievalTestSchedule",
            rule_name=f"heating-auto-retrieval-test-{environment_name}",
            description="Triggers test Viessmann retrieval (every 15 min, starting at 22:30 CET)",
            schedule=events.Schedule.expression(f"cron({test_schedule_cron})"),
        )
        rule.add_target(targets.LambdaFunction(auto_retrieval_test_fn))

        # Outputs
        CfnOutput(
            self,
            "TestTableName",
            value=test_table.table_name,
            description="Test DynamoDB table for auto-retrieval verification",
        )

        CfnOutput(
            self,
            "TestLambdaFunctionName",
            value=auto_retrieval_test_fn.function_name,
            description="Test Lambda function name — invoke manually for end-to-end testing",
        )

        CfnOutput(
            self,
            "TestFailureTopicArn",
            value=test_failure_topic.topic_arn,
            description="Test SNS topic for failure alerts (separate from production)",
        )
