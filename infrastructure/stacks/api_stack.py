"""API Gateway and Lambda execution role stack."""

from aws_cdk import (
    Stack,
    aws_apigatewayv2_alpha as apigw,
    aws_apigatewayv2_authorizers_alpha as apigw_auth,
    aws_apigatewayv2_integrations_alpha as apigw_integrations,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    CfnOutput,
    Duration,
    Fn,
    RemovalPolicy,
)
from constructs import Construct
import os


class APIStack(Stack):
    """Stack for API Gateway HTTP API and Lambda execution role."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment_name: str,
        cognito_user_pool_id: str,
        cognito_user_pool_client_id: str,
        cloudfront_domain: str | None = None,
        **kwargs
    ) -> None:
        """
        Initialize the API stack.

        Args:
            scope: The parent construct
            construct_id: The logical ID of the stack
            environment_name: The environment name (dev, prod, etc.)
            cognito_user_pool_id: The Cognito User Pool ID for JWT authorization
            cognito_user_pool_client_id: The Cognito User Pool App Client ID (audience) for JWT authorization
            cloudfront_domain: CloudFront distribution domain name for CORS (e.g. dxxxx.cloudfront.net)
            **kwargs: Additional arguments to pass to Stack
        """
        super().__init__(scope, construct_id, **kwargs)
        self.environment_name = environment_name

        # Create HTTP API (not REST API for cost efficiency)
        # CORS origins will include both localhost for development and CloudFront domain for production
        cors_origins = [
            "http://localhost:3000",  # Local development
            "http://localhost:8000",  # Local development (alternative port)
        ]

        # Add CloudFront origin for the deployed frontend (passed from FrontendStack)
        if cloudfront_domain:
            cors_origins.append(f"https://{cloudfront_domain}")
        
        http_api = apigw.HttpApi(
            self,
            "DataCollectionAPI",
            api_name=f"data-collection-api-{environment_name}",
            description="Data Collection Web Application API",
            cors_preflight=apigw.CorsPreflightOptions(
                allow_headers=["Content-Type", "Authorization"],
                allow_methods=[
                    apigw.CorsHttpMethod.GET,
                    apigw.CorsHttpMethod.POST,
                    apigw.CorsHttpMethod.OPTIONS,
                ],
                allow_origins=cors_origins,
                max_age=Duration.hours(1),
            ),
        )

        # Create JWT Authorizer using Cognito User Pool
        # For Cognito User Pool, we use the issuer URL format
        jwt_authorizer = apigw_auth.HttpJwtAuthorizer(
            id="DataCollectionJWTAuthorizer",
            # Audience must match the "aud" claim in tokens, which is the App Client ID (not the User Pool ID).
            jwt_audience=[cognito_user_pool_client_id],
            jwt_issuer=f"https://cognito-idp.eu-central-1.amazonaws.com/{cognito_user_pool_id}",
            identity_source=["$request.header.Authorization"],
        )

        # Create Lambda execution role with least-privilege permissions
        lambda_execution_role = iam.Role(
            self,
            "LambdaExecutionRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            role_name=f"data-collection-lambda-role-{environment_name}",
        )

        # Add basic Lambda execution policy for CloudWatch Logs
        lambda_execution_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSLambdaBasicExecutionRole"
            )
        )

        # Add DynamoDB permissions (least-privilege)
        # Get DynamoDB table ARN from CloudFormation export
        submissions_table_arn = Fn.import_value(
            f"DataCollectionSubmissionsTableArn-{environment_name}"
        )
        submissions_2025_table_arn = Fn.import_value(
            f"DataCollectionSubmissionsTableArn2025-{environment_name}"
        )

        lambda_execution_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:PutItem",
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                ],
                resources=[submissions_table_arn, submissions_2025_table_arn],
            )
        )

        # Get DynamoDB table name from CloudFormation export
        # Point the application to the historical table.
        submissions_table_name = Fn.import_value(
            f"DataCollectionSubmissionsTableName2025-{environment_name}"
        )

        # Create Lambda functions
        submit_handler = self._create_submit_handler(
            lambda_execution_role, submissions_table_name
        )
        history_handler = self._create_history_handler(
            lambda_execution_role, submissions_table_name
        )
        recent_handler = self._create_recent_handler(
            lambda_execution_role, submissions_table_name
        )

        # Wire Lambda functions to API Gateway routes with JWT authorization
        self._wire_routes(http_api, jwt_authorizer, submit_handler, history_handler, recent_handler)

        # Store references for use by other stacks
        self.http_api = http_api
        self.jwt_authorizer = jwt_authorizer
        self.lambda_execution_role = lambda_execution_role

        # Export API endpoint URL
        CfnOutput(
            self,
            "APIEndpoint",
            value=http_api.api_endpoint,
            export_name=f"DataCollectionAPIEndpoint-{environment_name}",
            description="API Gateway HTTP API endpoint URL",
        )

        # Export Lambda execution role ARN
        CfnOutput(
            self,
            "LambdaExecutionRoleArn",
            value=lambda_execution_role.role_arn,
            export_name=f"DataCollectionLambdaExecutionRoleArn-{environment_name}",
            description="Lambda execution role ARN",
        )

    def _create_submit_handler(
        self, lambda_execution_role: iam.Role, table_name: str
    ) -> lambda_.Function:
        """
        Create Lambda function for POST /submit endpoint.

        Args:
            lambda_execution_role: IAM role for Lambda execution
            table_name: DynamoDB table name

        Returns:
            Lambda Function construct
        """
        submit_fn = lambda_.Function(
            self,
            "SubmitHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="src.handlers.submit_handler.lambda_handler",
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", ".."),
                exclude=["cdk.out", ".git", ".venv", "node_modules", ".pytest_cache", ".hypothesis"],
            ),
            role=lambda_execution_role,
            environment={
                "SUBMISSIONS_TABLE": table_name,
            },
            timeout=Duration.seconds(30),
            memory_size=256,
            description="Lambda handler for form submission endpoint",
            # Configure retention for the *actual* Lambda log group:
            # /aws/lambda/<function name>
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        return submit_fn

    def _create_history_handler(
        self, lambda_execution_role: iam.Role, table_name: str
    ) -> lambda_.Function:
        """
        Create Lambda function for GET /history endpoint.

        Args:
            lambda_execution_role: IAM role for Lambda execution
            table_name: DynamoDB table name

        Returns:
            Lambda Function construct
        """
        history_fn = lambda_.Function(
            self,
            "HistoryHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="src.handlers.history_handler.lambda_handler",
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", ".."),
                exclude=["cdk.out", ".git", ".venv", "node_modules", ".pytest_cache", ".hypothesis"],
            ),
            role=lambda_execution_role,
            environment={
                "SUBMISSIONS_TABLE": table_name,
            },
            timeout=Duration.seconds(30),
            memory_size=256,
            description="Lambda handler for history retrieval endpoint",
            # Configure retention for the *actual* Lambda log group:
            # /aws/lambda/<function name>
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        return history_fn

    def _create_recent_handler(
        self, lambda_execution_role: iam.Role, table_name: str
    ) -> lambda_.Function:
        """
        Create Lambda function for GET /recent endpoint.

        Args:
            lambda_execution_role: IAM role for Lambda execution
            table_name: DynamoDB table name

        Returns:
            Lambda Function construct
        """
        recent_fn = lambda_.Function(
            self,
            "RecentHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="src.handlers.recent_handler.lambda_handler",
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", ".."),
                exclude=["cdk.out", ".git", ".venv", "node_modules", ".pytest_cache", ".hypothesis"],
            ),
            role=lambda_execution_role,
            environment={
                "SUBMISSIONS_TABLE": table_name,
            },
            timeout=Duration.seconds(30),
            memory_size=256,
            description="Lambda handler for recent submissions endpoint",
            # Configure retention for the *actual* Lambda log group:
            # /aws/lambda/<function name>
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        return recent_fn

    def _wire_routes(
        self,
        http_api: apigw.HttpApi,
        jwt_authorizer: apigw_auth.HttpJwtAuthorizer,
        submit_handler: lambda_.Function,
        history_handler: lambda_.Function,
        recent_handler: lambda_.Function,
    ) -> None:
        """
        Wire Lambda functions to API Gateway routes with JWT authorization.

        Args:
            http_api: HTTP API construct
            jwt_authorizer: JWT authorizer for route protection
            submit_handler: Lambda function for POST /submit
            history_handler: Lambda function for GET /history
            recent_handler: Lambda function for GET /recent
        """
        # POST /submit route
        http_api.add_routes(
            path="/submit",
            methods=[apigw.HttpMethod.POST],
            integration=apigw_integrations.HttpLambdaIntegration(
                "SubmitIntegration",
                submit_handler,
            ),
            authorizer=jwt_authorizer,
        )

        # GET /history route
        http_api.add_routes(
            path="/history",
            methods=[apigw.HttpMethod.GET],
            integration=apigw_integrations.HttpLambdaIntegration(
                "HistoryIntegration",
                history_handler,
            ),
            authorizer=jwt_authorizer,
        )

        # GET /recent route
        http_api.add_routes(
            path="/recent",
            methods=[apigw.HttpMethod.GET],
            integration=apigw_integrations.HttpLambdaIntegration(
                "RecentIntegration",
                recent_handler,
            ),
            authorizer=jwt_authorizer,
        )

    def _get_user_pool(self, user_pool_id: str):
        """
        Get Cognito User Pool from ID.

        Args:
            user_pool_id: The Cognito User Pool ID

        Returns:
            Cognito User Pool construct
        """
        from aws_cdk import aws_cognito as cognito

        return cognito.UserPool.from_user_pool_id(
            self, "ImportedUserPool", user_pool_id
        )
