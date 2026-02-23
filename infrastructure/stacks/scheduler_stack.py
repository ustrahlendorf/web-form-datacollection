"""Scheduler stack for automatic Viessmann data retrieval."""

from aws_cdk import (
    BundlingOptions,
    Stack,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_sns as sns,
    aws_ssm as ssm,
    CfnOutput,
    Duration,
)
from constructs import Construct
import os


class SchedulerStack(Stack):
    """Stack for EventBridge Rule and Lambda for daily Viessmann auto-retrieval."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment_name: str,
        viessmann_credentials_secret_arn: str,
        **kwargs,
    ) -> None:
        """
        Initialize the Scheduler stack.

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

        # Read config from SSM (parameters created by InitStack)
        schedule_cron = ssm.StringParameter.value_for_string_parameter(
            self, "/HeatingDataCollection/AutoRetrieval/ScheduleCron"
        )

        submissions_table_name = ssm.StringParameter.value_for_string_parameter(
            self, "/HeatingDataCollection/Submissions/Active/TableName"
        )

        submissions_table_arn = ssm.StringParameter.value_for_string_parameter(
            self, "/HeatingDataCollection/Submissions/Active/TableArn"
        )

        # SNS topic for failure alerts
        failure_topic = sns.Topic(
            self,
            "AutoRetrievalFailureTopic",
            display_name="Auto-retrieval Viessmann failure alerts",
            topic_name=f"heating-auto-retrieval-failure-{environment_name}",
        )

        # Lambda execution role
        lambda_role = iam.Role(
            self,
            "AutoRetrievalLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            role_name=f"heating-auto-retrieval-role-{environment_name}",
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
                resources=[submissions_table_arn],
            )
        )

        lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["sns:Publish"],
                resources=[failure_topic.topic_arn],
            )
        )

        # Lambda function
        asset_path = os.path.join(os.path.dirname(__file__), "..", "..")
        pythonpath = "backend/src"

        auto_retrieval_fn = lambda_.Function(
            self,
            "AutoRetrievalHandler",
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
                "SUBMISSIONS_TABLE": submissions_table_name,
                "VIESSMANN_CREDENTIALS_SECRET_ARN": viessmann_credentials_secret_arn,
                "AUTO_RETRIEVAL_FAILURE_TOPIC_ARN": failure_topic.topic_arn,
                "AUTO_RETRIEVAL_SSM_PREFIX": "/HeatingDataCollection/AutoRetrieval",
                "PYTHONPATH": pythonpath,
                "VIESSMANN_TOKEN_CACHE_PATH": "/tmp/viessmann/tokens.json",
            },
            timeout=Duration.minutes(15),
            memory_size=256,
            description="Lambda for scheduled Viessmann data retrieval and DynamoDB storage",
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        # EventBridge Rule
        rule = events.Rule(
            self,
            "AutoRetrievalSchedule",
            rule_name=f"heating-auto-retrieval-{environment_name}",
            description="Triggers daily Viessmann data retrieval",
            schedule=events.Schedule.expression(f"cron({schedule_cron})"),
        )

        rule.add_target(targets.LambdaFunction(auto_retrieval_fn))

        # Outputs
        CfnOutput(
            self,
            "FailureTopicArn",
            value=failure_topic.topic_arn,
            export_name=f"HeatingAutoRetrievalFailureTopicArn-{environment_name}",
            description="SNS topic ARN for failure alerts. Subscribe with email for notifications.",
        )
