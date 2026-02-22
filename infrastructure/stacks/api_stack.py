"""API Gateway and Lambda execution role stack."""

from aws_cdk import (
    BundlingOptions,
    Stack,
    aws_apigatewayv2_alpha as apigw,
    aws_apigatewayv2_authorizers_alpha as apigw_auth,
    aws_apigatewayv2_integrations_alpha as apigw_integrations,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_ssm as ssm,
    CfnOutput,
    Duration,
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
        viessmann_credentials_secret_arn: str | None = None,
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
            viessmann_credentials_secret_arn: ARN of Secrets Manager secret with VIESSMANN_CLIENT_ID,
                VIESSMANN_EMAIL, VIESSMANN_PASSWORD. If set, enables GET /heating/live endpoint.
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
        # Read active DynamoDB table ARN from SSM Parameter Store pointer (owned by DynamoDBStack).
        # This avoids tight coupling to CloudFormation exports/imports and makes rollovers deterministic.
        submissions_active_table_arn = ssm.StringParameter.value_for_string_parameter(
            self, "/HeatingDataCollection/Submissions/Active/TableArn"
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
                resources=[submissions_active_table_arn],
            )
        )

        # Add Secrets Manager permission for heating live Lambda (when Viessmann secret is configured)
        if viessmann_credentials_secret_arn:
            lambda_execution_role.add_to_policy(
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["secretsmanager:GetSecretValue"],
                    resources=[viessmann_credentials_secret_arn],
                )
            )

        # Read active DynamoDB table name from SSM Parameter Store pointer (owned by DynamoDBStack).
        submissions_table_name = ssm.StringParameter.value_for_string_parameter(
            self, "/HeatingDataCollection/Submissions/Active/TableName"
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
        heating_live_handler = (
            self._create_heating_live_handler(
                lambda_execution_role, viessmann_credentials_secret_arn
            )
            if viessmann_credentials_secret_arn
            else None
        )

        # Wire Lambda functions to API Gateway routes with JWT authorization
        self._wire_routes(
            http_api,
            jwt_authorizer,
            submit_handler,
            history_handler,
            recent_handler,
            heating_live_handler,
        )

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
        self,
        lambda_execution_role: iam.Role,
        table_name: str,
        passive_table_name: str | None = None,
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
                exclude=["cdk.out", ".git", ".venv", "node_modules", ".pytest_cache", ".hypothesis", ".jsii-package-cache"],
            ),
            role=lambda_execution_role,
            environment={
                "SUBMISSIONS_TABLE": table_name,
                **(
                    {"PASSIVE_SUBMISSIONS_TABLE": passive_table_name}
                    if passive_table_name
                    else {}
                ),
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
        self,
        lambda_execution_role: iam.Role,
        table_name: str,
        passive_table_name: str | None = None,
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
                exclude=["cdk.out", ".git", ".venv", "node_modules", ".pytest_cache", ".hypothesis", ".jsii-package-cache"],
            ),
            role=lambda_execution_role,
            environment={
                "SUBMISSIONS_TABLE": table_name,
                **(
                    {"PASSIVE_SUBMISSIONS_TABLE": passive_table_name}
                    if passive_table_name
                    else {}
                ),
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
        self,
        lambda_execution_role: iam.Role,
        table_name: str,
        passive_table_name: str | None = None,
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
                exclude=["cdk.out", ".git", ".venv", "node_modules", ".pytest_cache", ".hypothesis", ".jsii-package-cache"],
            ),
            role=lambda_execution_role,
            environment={
                "SUBMISSIONS_TABLE": table_name,
                **(
                    {"PASSIVE_SUBMISSIONS_TABLE": passive_table_name}
                    if passive_table_name
                    else {}
                ),
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
        heating_live_handler: lambda_.Function | None = None,
    ) -> None:
        """
        Wire Lambda functions to API Gateway routes with JWT authorization.

        Args:
            http_api: HTTP API construct
            jwt_authorizer: JWT authorizer for route protection
            submit_handler: Lambda function for POST /submit
            history_handler: Lambda function for GET /history
            recent_handler: Lambda function for GET /recent
            heating_live_handler: Optional Lambda for GET /heating/live
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

        # GET /heating/live route (optional; requires Viessmann credentials secret)
        if heating_live_handler is not None:
            http_api.add_routes(
                path="/heating/live",
                methods=[apigw.HttpMethod.GET],
                integration=apigw_integrations.HttpLambdaIntegration(
                    "HeatingLiveIntegration",
                    heating_live_handler,
                ),
                authorizer=jwt_authorizer,
            )

    def _create_heating_live_handler(
        self,
        lambda_execution_role: iam.Role,
        viessmann_credentials_secret_arn: str,
    ) -> lambda_.Function:
        """
        Create Lambda function for GET /heating/live endpoint.

        Fetches heating values from Viessmann IoT API. Requires backend package
        and PYTHONPATH for backend.iot_data. Credentials from Secrets Manager.
        """
        asset_path = os.path.join(os.path.dirname(__file__), "..", "..")
        # Lambda extracts asset to /var/task; backend package is at backend/src/backend/
        pythonpath = "backend/src"

        heating_live_fn = lambda_.Function(
            self,
            "HeatingLiveHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="src.handlers.heating_live_handler.lambda_handler",
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
            role=lambda_execution_role,
            environment={
                "VIESSMANN_CREDENTIALS_SECRET_ARN": viessmann_credentials_secret_arn,
                "PYTHONPATH": pythonpath,
                # Lambda filesystem is read-only except /tmp; token cache must use writable path.
                "VIESSMANN_TOKEN_CACHE_PATH": "/tmp/viessmann/tokens.json",
            },
            timeout=Duration.seconds(60),
            memory_size=256,
            description="Lambda handler for heating live data endpoint",
            log_retention=logs.RetentionDays.ONE_WEEK,
        )

        return heating_live_fn

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
