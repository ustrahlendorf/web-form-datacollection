"""Cognito User Pool stack for authentication."""

from aws_cdk import (
    Stack,
    aws_cognito as cognito,
    CfnOutput,
)
from constructs import Construct


class CognitoStack(Stack):
    """Stack for Cognito User Pool and authentication configuration."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment_name: str,
        **kwargs
    ) -> None:
        """
        Initialize the Cognito stack.

        Args:
            scope: The parent construct
            construct_id: The logical ID of the stack
            environment_name: The environment name (dev, prod, etc.)
            **kwargs: Additional arguments to pass to Stack
        """
        super().__init__(scope, construct_id, **kwargs)
        self.environment_name = environment_name

        # Create Cognito User Pool with self-signup disabled (admin/invite only)
        user_pool = cognito.UserPool(
            self,
            "DataCollectionUserPool",
            user_pool_name=f"data-collection-{environment_name}",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=False,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=None,  # Retain on stack deletion for safety
        )

        # Create User Pool Client for frontend
        # Callback URLs include both localhost for development and CloudFront domain for production
        callback_urls = ["http://localhost:3000", "http://localhost:8000"]
        logout_urls = ["http://localhost:3000", "http://localhost:8000"]
        
        # Add CloudFront domain if available (will be set during deployment)
        import os
        cloudfront_domain = os.environ.get("CLOUDFRONT_DOMAIN")
        if cloudfront_domain:
            callback_urls.append(f"https://{cloudfront_domain}")
            logout_urls.append(f"https://{cloudfront_domain}")
        
        user_pool_client = user_pool.add_client(
            "DataCollectionClient",
            user_pool_client_name=f"data-collection-frontend-{environment_name}",
            auth_flows=cognito.AuthFlow(
                user_password=True,
            ),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    authorization_code_grant=True,
                    implicit_code_grant=False,
                ),
                # Frontend requests: openid + profile + email
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.PROFILE,
                    cognito.OAuthScope.EMAIL,
                ],
                callback_urls=callback_urls,
                logout_urls=logout_urls,
            ),
            prevent_user_existence_errors=True,
            generate_secret=False,  # No secret for public frontend client
        )

        # Configure Hosted UI
        user_pool.add_domain(
            "DataCollectionDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=f"data-collection-{environment_name}",
            ),
        )

        # Export User Pool ID for API Gateway JWT Authorizer
        CfnOutput(
            self,
            "UserPoolId",
            value=user_pool.user_pool_id,
            export_name=f"DataCollectionUserPoolId-{environment_name}",
            description="Cognito User Pool ID for JWT authorization",
        )

        # Export User Pool Client ID for frontend
        CfnOutput(
            self,
            "UserPoolClientId",
            value=user_pool_client.user_pool_client_id,
            export_name=f"DataCollectionUserPoolClientId-{environment_name}",
            description="Cognito User Pool Client ID for frontend",
        )

        # Export User Pool ARN for reference
        CfnOutput(
            self,
            "UserPoolArn",
            value=user_pool.user_pool_arn,
            export_name=f"DataCollectionUserPoolArn-{environment_name}",
            description="Cognito User Pool ARN",
        )

        # Export Hosted UI domain
        CfnOutput(
            self,
            "HostedUiDomain",
            value=f"https://data-collection-{environment_name}.auth.eu-central-1.amazoncognito.com",
            export_name=f"DataCollectionHostedUiDomain-{environment_name}",
            description="Cognito Hosted UI domain",
        )

        # Store references for use by other stacks
        self.user_pool = user_pool
        self.user_pool_client = user_pool_client
