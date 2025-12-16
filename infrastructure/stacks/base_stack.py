"""Base CDK Stack with common configuration for all environments."""

from aws_cdk import Stack
from constructs import Construct
from infrastructure.stacks.cognito_stack import CognitoStack
from infrastructure.stacks.dynamodb_stack import DynamoDBStack
from infrastructure.stacks.api_stack import APIStack
from infrastructure.stacks.frontend_stack import FrontendStack


class BaseStack(Stack):
    """Base stack class with common configuration for all environments."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment_name: str,
        **kwargs
    ) -> None:
        """
        Initialize the base stack.

        Args:
            scope: The parent construct
            construct_id: The logical ID of the stack
            environment_name: The environment name (dev, prod, etc.)
            **kwargs: Additional arguments to pass to Stack
        """
        super().__init__(scope, construct_id, **kwargs)
        self.environment_name = environment_name

        # Create Cognito stack for authentication
        self.cognito_stack = CognitoStack(
            scope,
            f"DataCollectionCognito-{environment_name}",
            environment_name=environment_name,
        )

        # Create DynamoDB stack for data persistence
        self.dynamodb_stack = DynamoDBStack(
            scope,
            f"DataCollectionDynamoDB-{environment_name}",
            environment_name=environment_name,
        )

        # Create API Gateway and Lambda execution role stack
        self.api_stack = APIStack(
            scope,
            f"DataCollectionAPI-{environment_name}",
            environment_name=environment_name,
            cognito_user_pool_id=self.cognito_stack.user_pool.user_pool_id,
        )

        # Create Frontend stack for S3 and CloudFront
        self.frontend_stack = FrontendStack(
            scope,
            f"DataCollectionFrontend-{environment_name}",
            environment_name=environment_name,
        )
