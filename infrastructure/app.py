"""AWS CDK Application for Data Collection Web Application (dev-only)."""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from aws_cdk import App, Environment, Tags

from infrastructure.stacks.api_stack import APIStack
from infrastructure.stacks.cognito_stack import CognitoStack
from infrastructure.stacks.datalake_stack import DataLakeStack
from infrastructure.stacks.dynamodb_stack import DynamoDBStack
from infrastructure.stacks.frontend_stack import FrontendStack


def create_app() -> App:
    """
    Create and configure the CDK App (dev-only).

    Returns:
        Configured CDK App instance
    """
    app = App()

    # Global tags applied to all stacks in this app
    Tags.of(app).add("Project", "data-collection")
    Tags.of(app).add("ManagedBy", "CDK")
    Tags.of(app).add("Creator", "uwe-strahlendorf")

    # Define the environment configuration.
    # CDK requires an account for non-environment-agnostic stacks; the CDK CLI
    # typically provides CDK_DEFAULT_ACCOUNT/CDK_DEFAULT_REGION automatically.
    env_config = Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "eu-central-1"),
    )

    environment_name = "dev"

    # Create component stacks for development environment
    cognito_stack = CognitoStack(
        app,
        f"DataCollectionCognito-{environment_name}",
        environment_name=environment_name,
        env=env_config,
        description="Data Collection Web Application - Cognito (dev)",
    )

    dynamodb_stack = DynamoDBStack(
        app,
        f"DataCollectionDynamoDB-{environment_name}",
        environment_name=environment_name,
        env=env_config,
        description="Data Collection Web Application - DynamoDB (dev)",
    )

    datalake_stack = DataLakeStack(
        app,
        f"DataCollectionDataLake-{environment_name}",
        environment_name=environment_name,
        env=env_config,
        description="Data Collection Web Application - DataLake (dev)",
    )

    frontend_stack = FrontendStack(
        app,
        f"DataCollectionFrontend-{environment_name}",
        environment_name=environment_name,
        env=env_config,
        description="Data Collection Web Application - Frontend (dev)",
    )

    api_stack = APIStack(
        app,
        f"DataCollectionAPI-{environment_name}",
        environment_name=environment_name,
        cognito_user_pool_id=cognito_stack.user_pool.user_pool_id,
        cognito_user_pool_client_id=cognito_stack.user_pool_client.user_pool_client_id,
        cloudfront_domain=frontend_stack.distribution.domain_name,
        env=env_config,
        description="Data Collection Web Application - API (dev)",
    )

    # Ensure deployment ordering across stacks that use exports/imports.
    api_stack.add_dependency(frontend_stack)
    api_stack.add_dependency(cognito_stack)
    api_stack.add_dependency(dynamodb_stack)
    api_stack.add_dependency(datalake_stack)

    return app


if __name__ == "__main__":
    create_app().synth()
