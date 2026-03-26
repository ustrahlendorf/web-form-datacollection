"""Scheduler frequent stack for production auto-retrieval with multiple runs per day.

Creates a DynamoDB table and Lambda for frequent auto-retrieval within active windows.
EventBridge Rule triggers multiple runs per day. Uses a dedicated SNS topic for failure alerts.
"""

from aws_cdk import (
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

from infrastructure.config.heating_lambda_env import (
    BACKEND_PYTHONPATH,
    VIESSMANN_TOKEN_CACHE_PATH,
)
from infrastructure.cdk_constructs.python_lambda_asset import (
    heating_lambda_bundling,
    python_lambda_code_from_repo,
)
from infrastructure.stacks.ssm_contract import (
    AUTO_RETRIEVAL_SEGMENTS,
    DEFAULT_SSM_NAMESPACE_PREFIX,
    normalize_namespace_prefix,
    ssm_parameter_arn_from_segments,
    ssm_parameter_name,
)


class SchedulerFrequentStack(Stack):
    """Stack for frequent auto-retrieval Lambda with DynamoDB table and SNS topic."""

    DEFAULT_SSM_PREFIX = DEFAULT_SSM_NAMESPACE_PREFIX

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment_name: str,
        viessmann_credentials_secret_arn: str,
        appconfig_application_id: str,
        appconfig_environment_id: str,
        appconfig_profile_id: str,
        ssm_namespace_prefix: str = DEFAULT_SSM_PREFIX,
        **kwargs,
    ) -> None:
        """
        Initialize the Scheduler frequent stack.

        Args:
            scope: The parent construct
            construct_id: The logical ID of the stack
            environment_name: The environment name (dev, prod, etc.)
            viessmann_credentials_secret_arn: ARN of Secrets Manager secret with
                VIESSMANN_CLIENT_ID, VIESSMANN_EMAIL, VIESSMANN_PASSWORD
            appconfig_application_id: AppConfig application identifier
            appconfig_environment_id: AppConfig environment identifier
            appconfig_profile_id: AppConfig configuration profile identifier
            ssm_namespace_prefix: Root SSM namespace prefix (for example /HeatingDataCollection)
            **kwargs: Additional arguments to pass to Stack
        """
        super().__init__(scope, construct_id, **kwargs)
        self.environment_name = environment_name
        self.ssm_prefix = normalize_namespace_prefix(ssm_namespace_prefix)
        self.auto_retrieval_ssm_prefix = ssm_parameter_name(
            self.ssm_prefix, *AUTO_RETRIEVAL_SEGMENTS
        )

        # Read frequent schedule from SSM (parameter created by InitStack)
        frequent_schedule_cron = ssm.StringParameter.value_for_string_parameter(
            self,
            ssm_parameter_name(self.ssm_prefix, *AUTO_RETRIEVAL_SEGMENTS, "FrequentScheduleCron"),
        )

        # DynamoDB table — same schema as production (user_id, timestamp_utc)
        frequent_table = dynamodb.Table(
            self,
            "SubmissionsAutoRetrievalFrequentTable",
            table_name=f"submissions-auto-retrieval-frequent-{environment_name}",
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

        # SNS topic for failure alerts
        frequent_failure_topic = sns.Topic(
            self,
            "AutoRetrievalFrequentFailureTopic",
            display_name="Auto-retrieval frequent failure alerts",
            topic_name=f"heating-auto-retrieval-frequent-failure-{environment_name}",
        )

        # Lambda execution role — access to frequent table and SNS
        lambda_role = iam.Role(
            self,
            "AutoRetrievalFrequentLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            role_name=f"heating-auto-retrieval-frequent-role-{environment_name}",
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
                    ssm_parameter_arn_from_segments(
                        self.region,
                        self.account,
                        self.ssm_prefix,
                        *AUTO_RETRIEVAL_SEGMENTS,
                        "*",
                    )
                ],
            )
        )

        appconfig_configuration_arn = (
            f"arn:aws:appconfig:{self.region}:{self.account}:application/"
            f"{appconfig_application_id}/environment/{appconfig_environment_id}"
            f"/configuration/{appconfig_profile_id}"
        )
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["appconfig:StartConfigurationSession"],
                resources=[appconfig_configuration_arn],
            )
        )
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["appconfig:GetLatestConfiguration"],
                resources=["*"],
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
                resources=[frequent_table.table_arn],
            )
        )

        lambda_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["sns:Publish"],
                resources=[frequent_failure_topic.topic_arn],
            )
        )

        # Lambda function — same handler/code as production
        appconfig_agent_layer_arn = os.environ.get("APPCONFIG_AGENT_EXTENSION_LAYER_ARN", "").strip()
        use_appconfig_agent = "true" if appconfig_agent_layer_arn else "false"

        auto_retrieval_frequent_fn = lambda_.Function(
            self,
            "AutoRetrievalFrequentHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="src.handlers.auto_retrieval_handler.lambda_handler",
            code=python_lambda_code_from_repo(bundling=heating_lambda_bundling()),
            role=lambda_role,
            environment={
                "SUBMISSIONS_TABLE": frequent_table.table_name,
                "VIESSMANN_CREDENTIALS_SECRET_ARN": viessmann_credentials_secret_arn,
                "ONCE_DAILY": "false",
                "AUTO_RETRIEVAL_FAILURE_TOPIC_ARN": frequent_failure_topic.topic_arn,
                "AUTO_RETRIEVAL_SSM_PREFIX": self.auto_retrieval_ssm_prefix,
                "AUTO_RETRIEVAL_ENABLE_SSM_FALLBACK": "false",
                "AUTO_RETRIEVAL_SKIP_DUPLICATE": "false",
                "ACTIVE_WINDOWS_PARAM": "FrequentActiveWindows",
                "AUTO_RETRIEVAL_APPCONFIG_APPLICATION_ID": appconfig_application_id,
                "AUTO_RETRIEVAL_APPCONFIG_ENVIRONMENT_ID": appconfig_environment_id,
                "AUTO_RETRIEVAL_APPCONFIG_PROFILE_ID": appconfig_profile_id,
                "AUTO_RETRIEVAL_USE_APPCONFIG_AGENT": use_appconfig_agent,
                "AUTO_RETRIEVAL_APPCONFIG_AGENT_ENDPOINT": "http://127.0.0.1:2772",
                "AUTO_RETRIEVAL_APPCONFIG_AGENT_TIMEOUT_SECONDS": "2.0",
                "AUTO_RETRIEVAL_ACTIVE_WINDOWS_TIMEZONE": "Europe/Berlin",
                "PYTHONPATH": BACKEND_PYTHONPATH,
                "VIESSMANN_TOKEN_CACHE_PATH": VIESSMANN_TOKEN_CACHE_PATH,
            },
            timeout=Duration.minutes(15),
            memory_size=256,
            description="Frequent Lambda for Viessmann auto-retrieval (multiple runs per day)",
            log_retention=logs.RetentionDays.ONE_WEEK,
        )
        if appconfig_agent_layer_arn:
            appconfig_agent_layer = lambda_.LayerVersion.from_layer_version_arn(
                self,
                "AppConfigAgentExtensionLayer",
                appconfig_agent_layer_arn,
            )
            auto_retrieval_frequent_fn.add_layers(appconfig_agent_layer)

        # EventBridge Rule — triggers Lambda on schedule (multiple runs per day)
        rule = events.Rule(
            self,
            "AutoRetrievalFrequentSchedule",
            rule_name=f"heating-auto-retrieval-frequent-{environment_name}",
            description="Triggers frequent Viessmann retrieval (every 15 min within active windows)",
            schedule=events.Schedule.expression(f"cron({frequent_schedule_cron})"),
        )
        rule.add_target(targets.LambdaFunction(auto_retrieval_frequent_fn))

        # Outputs
        CfnOutput(
            self,
            "FrequentTableName",
            value=frequent_table.table_name,
            description="DynamoDB table for frequent auto-retrieval",
        )

        CfnOutput(
            self,
            "FrequentLambdaFunctionName",
            value=auto_retrieval_frequent_fn.function_name,
            description="Frequent Lambda function name — invoke manually for testing",
        )

        CfnOutput(
            self,
            "FrequentFailureTopicArn",
            value=frequent_failure_topic.topic_arn,
            description="SNS topic for frequent failure alerts",
        )
