"""Once-daily scheduler stack for automatic Viessmann data retrieval."""

from aws_cdk import (
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
    SUBMISSIONS_ACTIVE_TABLE_ARN_SEGMENTS,
    SUBMISSIONS_ACTIVE_TABLE_NAME_SEGMENTS,
    normalize_namespace_prefix,
    ssm_parameter_arn_from_segments,
    ssm_parameter_name,
)


class SchedulerOnceDailyStack(Stack):
    """Stack for EventBridge Rule and Lambda for daily Viessmann auto-retrieval."""

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
        Initialize the Scheduler stack.

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

        # Read config from SSM (parameters created by InitStack)
        schedule_cron = ssm.StringParameter.value_for_string_parameter(
            self, ssm_parameter_name(self.ssm_prefix, *AUTO_RETRIEVAL_SEGMENTS, "ScheduleCron")
        )

        submissions_table_name = ssm.StringParameter.value_for_string_parameter(
            self, ssm_parameter_name(self.ssm_prefix, *SUBMISSIONS_ACTIVE_TABLE_NAME_SEGMENTS)
        )

        submissions_table_arn = ssm.StringParameter.value_for_string_parameter(
            self, ssm_parameter_name(self.ssm_prefix, *SUBMISSIONS_ACTIVE_TABLE_ARN_SEGMENTS)
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
        appconfig_agent_layer_arn = os.environ.get("APPCONFIG_AGENT_EXTENSION_LAYER_ARN", "").strip()
        use_appconfig_agent = "true" if appconfig_agent_layer_arn else "false"

        auto_retrieval_fn = lambda_.Function(
            self,
            "AutoRetrievalHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="lambdas.auto_retrieval.handler.lambda_handler",
            code=python_lambda_code_from_repo(bundling=heating_lambda_bundling()),
            role=lambda_role,
            environment={
                "SUBMISSIONS_TABLE": submissions_table_name,
                "VIESSMANN_CREDENTIALS_SECRET_ARN": viessmann_credentials_secret_arn,
                "ONCE_DAILY": "true",
                "AUTO_RETRIEVAL_FAILURE_TOPIC_ARN": failure_topic.topic_arn,
                "AUTO_RETRIEVAL_SSM_PREFIX": self.auto_retrieval_ssm_prefix,
                "AUTO_RETRIEVAL_ENABLE_SSM_FALLBACK": "false",
                "AUTO_RETRIEVAL_APPCONFIG_APPLICATION_ID": appconfig_application_id,
                "AUTO_RETRIEVAL_APPCONFIG_ENVIRONMENT_ID": appconfig_environment_id,
                "AUTO_RETRIEVAL_APPCONFIG_PROFILE_ID": appconfig_profile_id,
                "AUTO_RETRIEVAL_USE_APPCONFIG_AGENT": use_appconfig_agent,
                "AUTO_RETRIEVAL_APPCONFIG_AGENT_ENDPOINT": "http://127.0.0.1:2772",
                "AUTO_RETRIEVAL_APPCONFIG_AGENT_TIMEOUT_SECONDS": "2.0",
                "PYTHONPATH": BACKEND_PYTHONPATH,
                "VIESSMANN_TOKEN_CACHE_PATH": VIESSMANN_TOKEN_CACHE_PATH,
            },
            timeout=Duration.minutes(15),
            memory_size=256,
            description="Lambda for scheduled Viessmann data retrieval and DynamoDB storage",
            log_retention=logs.RetentionDays.ONE_WEEK,
        )
        if appconfig_agent_layer_arn:
            appconfig_agent_layer = lambda_.LayerVersion.from_layer_version_arn(
                self,
                "AppConfigAgentExtensionLayer",
                appconfig_agent_layer_arn,
            )
            auto_retrieval_fn.add_layers(appconfig_agent_layer)

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
