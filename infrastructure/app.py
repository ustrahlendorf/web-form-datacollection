"""AWS CDK Application for Data Collection Web Application."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from aws_cdk import (
    App,
    Environment,
    Stack,
)
from constructs import Construct
from infrastructure.stacks.base_stack import BaseStack


class DevStack(BaseStack):
    """Development environment stack."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        """
        Initialize the development stack.

        Args:
            scope: The parent construct
            construct_id: The logical ID of the stack
            **kwargs: Additional arguments to pass to BaseStack
        """
        super().__init__(scope, construct_id, environment_name="dev", **kwargs)


class ProdStack(BaseStack):
    """Production environment stack."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        """
        Initialize the production stack.

        Args:
            scope: The parent construct
            construct_id: The logical ID of the stack
            **kwargs: Additional arguments to pass to BaseStack
        """
        super().__init__(scope, construct_id, environment_name="prod", **kwargs)


def create_app() -> App:
    """
    Create and configure the CDK App.

    Returns:
        Configured CDK App instance
    """
    app = App()

    # Define the environment configuration for eu-central-1
    env_config = Environment(
        region="eu-central-1",
    )

    # Create development stack
    DevStack(
        app,
        "DataCollectionWebAppDev",
        env=env_config,
        description="Data Collection Web Application - Development Environment",
    )

    # Create production stack
    ProdStack(
        app,
        "DataCollectionWebAppProd",
        env=env_config,
        description="Data Collection Web Application - Production Environment",
    )

    return app


if __name__ == "__main__":
    app = create_app()
    app.synth()
