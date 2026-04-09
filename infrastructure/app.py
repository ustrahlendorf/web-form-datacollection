"""AWS CDK Application for Data Collection Web Application (dev-only)."""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from aws_cdk import App, Environment, Tags

from infrastructure.stacks.appconfig_stack import AppConfigStack
from infrastructure.stacks.api_stack import APIStack
from infrastructure.stacks.cognito_stack import CognitoStack
from infrastructure.stacks.datalake_stack import DataLakeStack
from infrastructure.stacks.dynamodb_stack import DynamoDBStack
from infrastructure.stacks.frontend_stack import FrontendStack
from infrastructure.stacks.init_stack import InitStack
from infrastructure.stacks.scheduler_once_daily_stack import SchedulerOnceDailyStack
from infrastructure.stacks.scheduler_frequent_stack import SchedulerFrequentStack


def _normalize_ssm_namespace_prefix(prefix: str) -> str:
    """Normalize SSM namespace prefix to '/segment[/segment...]' format."""
    normalized = prefix.strip()
    if not normalized:
        raise SystemExit(
            "SSM_NAMESPACE_PREFIX must not be empty. "
            "Set it before running 'cdk synth/deploy'."
        )
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if normalized != "/":
        normalized = normalized.rstrip("/")
    return normalized


def create_app() -> App:
    """
    Create and configure the CDK App (dev-only).

    Returns:
        Configured CDK App instance
    """
    app = App()

    # Define the environment configuration.
    # CDK requires an account for non-environment-agnostic stacks; the CDK CLI
    # typically provides CDK_DEFAULT_ACCOUNT/CDK_DEFAULT_REGION automatically.
    env_config = Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "eu-central-1"),
    )

    environment_name = "dev"

    # Global tags (propagate to taggable resources). Activate keys in AWS Billing
    # console under Cost allocation tags for Cost Explorer / chargeback.
    Tags.of(app).add("Project", "data-collection")
    Tags.of(app).add("Environment", environment_name)
    Tags.of(app).add("ManagedBy", "CDK")
    Tags.of(app).add("Creator", "uwe-strahlendorf")
    _cost_center = os.environ.get("COST_CENTER", "").strip()
    if _cost_center:
        Tags.of(app).add("CostCenter", _cost_center)
    _application = os.environ.get("APPLICATION", "").strip()
    if _application:
        Tags.of(app).add("Application", _application)
    _owner = os.environ.get("OWNER", "").strip()
    if _owner:
        Tags.of(app).add("Owner", _owner)
    ssm_namespace_prefix = _normalize_ssm_namespace_prefix(
        os.environ.get("SSM_NAMESPACE_PREFIX", "/HeatingDataCollection")
    )

    # External configuration for DynamoDB table naming (active/passive).
    # These MUST be provided at deploy time so we never silently fall back to a hardcoded year.
    active_submissions_table_name = os.environ.get("ACTIVE_SUBMISSIONS_TABLE_NAME")
    passive_submissions_table_name = os.environ.get("PASSIVE_SUBMISSIONS_TABLE_NAME")

    missing = [
        name
        for name, value in [
            ("ACTIVE_SUBMISSIONS_TABLE_NAME", active_submissions_table_name),
            ("PASSIVE_SUBMISSIONS_TABLE_NAME", passive_submissions_table_name),
        ]
        if not value
    ]
    if missing:
        raise SystemExit(
            "Missing required environment variables for DynamoDB naming: "
            + ", ".join(missing)
            + ". "
            + "Set them before running 'cdk synth/deploy'."
        )

    # Create component stacks for development environment
    init_stack = InitStack(
        app,
        f"DataCollectionInit-{environment_name}",
        environment_name=environment_name,
        ssm_namespace_prefix=ssm_namespace_prefix,
        env=env_config,
        description="Data Collection Web Application - Init (dev)",
    )
    Tags.of(init_stack).add("Component", "init")

    appconfig_stack = AppConfigStack(
        app,
        f"DataCollectionAppConfig-{environment_name}",
        environment_name=environment_name,
        env=env_config,
        description="Data Collection Web Application - AppConfig (dev)",
    )
    Tags.of(appconfig_stack).add("Component", "appconfig")

    cognito_stack = CognitoStack(
        app,
        f"DataCollectionCognito-{environment_name}",
        environment_name=environment_name,
        env=env_config,
        description="Data Collection Web Application - Cognito (dev)",
    )
    Tags.of(cognito_stack).add("Component", "auth")

    dynamodb_stack = DynamoDBStack(
        app,
        f"DataCollectionDynamoDB-{environment_name}",
        environment_name=environment_name,
        ssm_namespace_prefix=ssm_namespace_prefix,
        active_submissions_table_name=str(active_submissions_table_name),
        passive_submissions_table_name=str(passive_submissions_table_name),
        env=env_config,
        description="Data Collection Web Application - DynamoDB (dev)",
    )
    Tags.of(dynamodb_stack).add("Component", "datastore")

    datalake_stack = DataLakeStack(
        app,
        f"DataCollectionDataLake-{environment_name}",
        environment_name=environment_name,
        env=env_config,
        description="Data Collection Web Application - DataLake (dev)",
    )
    Tags.of(datalake_stack).add("Component", "datalake")

    frontend_stack = FrontendStack(
        app,
        f"DataCollectionFrontend-{environment_name}",
        environment_name=environment_name,
        env=env_config,
        description="Data Collection Web Application - Frontend (dev)",
    )
    Tags.of(frontend_stack).add("Component", "frontend")

    viessmann_credentials_secret_arn = os.environ.get("VIESSMANN_CREDENTIALS_SECRET_ARN")
    auto_retrieval_frequent_rule_name = (
        f"heating-auto-retrieval-frequent-{environment_name}"
    )
    auto_retrieval_daily_schedule_name = (
        f"heating-auto-retrieval-{environment_name}"
        if viessmann_credentials_secret_arn
        else None
    )

    api_stack = APIStack(
        app,
        f"DataCollectionAPI-{environment_name}",
        environment_name=environment_name,
        ssm_namespace_prefix=ssm_namespace_prefix,
        cognito_user_pool_id=cognito_stack.user_pool.user_pool_id,
        cognito_user_pool_client_id=cognito_stack.user_pool_client.user_pool_client_id,
        appconfig_application_id=appconfig_stack.appconfig_application.ref,
        appconfig_environment_id=appconfig_stack.appconfig_environment.ref,
        appconfig_profile_id=appconfig_stack.appconfig_profile.ref,
        appconfig_deployment_strategy_id=appconfig_stack.deployment_strategy.ref,
        auto_retrieval_frequent_rule_name=auto_retrieval_frequent_rule_name,
        auto_retrieval_daily_schedule_name=auto_retrieval_daily_schedule_name,
        cloudfront_domain=frontend_stack.distribution.domain_name,
        viessmann_credentials_secret_arn=viessmann_credentials_secret_arn,
        env=env_config,
        description="Data Collection Web Application - API (dev)",
    )
    Tags.of(api_stack).add("Component", "api")

    if viessmann_credentials_secret_arn:
        scheduler_once_daily_stack = SchedulerOnceDailyStack(
            app,
            f"DataCollectionScheduler-{environment_name}",
            environment_name=environment_name,
            ssm_namespace_prefix=ssm_namespace_prefix,
            viessmann_credentials_secret_arn=viessmann_credentials_secret_arn,
            appconfig_application_id=appconfig_stack.appconfig_application.ref,
            appconfig_environment_id=appconfig_stack.appconfig_environment.ref,
            appconfig_profile_id=appconfig_stack.appconfig_profile.ref,
            env=env_config,
            description="Data Collection - Auto-retrieval Scheduler (dev)",
        )
        Tags.of(scheduler_once_daily_stack).add("Component", "scheduler-daily")
        scheduler_once_daily_stack.add_dependency(init_stack)
        scheduler_once_daily_stack.add_dependency(dynamodb_stack)
        scheduler_once_daily_stack.add_dependency(appconfig_stack)

        # Scheduler frequent stack — production auto-retrieval with multiple runs per day
        scheduler_frequent_stack = SchedulerFrequentStack(
            app,
            f"DataCollectionSchedulerFrequent-{environment_name}",
            environment_name=environment_name,
            ssm_namespace_prefix=ssm_namespace_prefix,
            viessmann_credentials_secret_arn=viessmann_credentials_secret_arn,
            appconfig_application_id=appconfig_stack.appconfig_application.ref,
            appconfig_environment_id=appconfig_stack.appconfig_environment.ref,
            appconfig_profile_id=appconfig_stack.appconfig_profile.ref,
            env=env_config,
            description="Data Collection - Auto-retrieval Frequent (dev)",
        )
        Tags.of(scheduler_frequent_stack).add("Component", "scheduler-frequent")
        scheduler_frequent_stack.add_dependency(init_stack)
        scheduler_frequent_stack.add_dependency(appconfig_stack)

    # Ensure deployment ordering across stacks that use exports/imports.
    # InitStack owns the stable SSM "contract" parameters and must exist first so other stacks
    # can safely read/extend the namespace over time.
    appconfig_stack.add_dependency(init_stack)
    dynamodb_stack.add_dependency(init_stack)
    api_stack.add_dependency(init_stack)
    api_stack.add_dependency(frontend_stack)
    api_stack.add_dependency(cognito_stack)
    api_stack.add_dependency(dynamodb_stack)
    api_stack.add_dependency(datalake_stack)
    api_stack.add_dependency(appconfig_stack)

    return app


if __name__ == "__main__":
    create_app().synth()
