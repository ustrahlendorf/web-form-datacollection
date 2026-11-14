from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_authorizers as authorizers,
    aws_apigatewayv2_integrations as integrations,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_logs as logs,
)
from constructs import Construct

from infrastructure.cdk_constructs.python_lambda_asset import python_lambda_code_from_repo
from infrastructure.config.heating_lambda_env import BACKEND_PYTHONPATH


class HeizungSettingsStack(Stack):
    """API Gateway (HTTP API, IAM-Auth) -> Lambda -> DynamoDB."""

    def __init__(self, scope: Construct, construct_id: str, *, system_id: str = "haus", **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Daten -------------------------------------------------------
        # Die frühere Migrations-Tabelle (SettingsTable) ist aus dem Stack entfernt; sie bleibt
        # wegen RETAIN bestehen und wird separat gelöscht.
        parameter_table = dynamodb.TableV2(
            self, "ParameterTable",
            table_name="Settings-HeizungParameter",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing=dynamodb.Billing.on_demand(),
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
            deletion_protection=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # --- Lambda-Funktionen ------------------------------------------
        def make_function(name: str, handler: str, description: str) -> _lambda.Function:
            return _lambda.Function(
                self, name,
                description=description,
                runtime=_lambda.Runtime.PYTHON_3_13,
                architecture=_lambda.Architecture.ARM_64,
                handler=handler,
                code=python_lambda_code_from_repo(),
                memory_size=256,
                timeout=Duration.seconds(10),
                environment={
                    "TABLE_NAME": parameter_table.table_name,
                    "SYSTEM_ID": system_id,
                    "PYTHONPATH": BACKEND_PYTHONPATH,
                },
                log_group=logs.LogGroup(
                    self, f"{name}Logs",
                    retention=logs.RetentionDays.ONE_MONTH,
                    removal_policy=RemovalPolicy.DESTROY,
                ),
            )

        writer = make_function("WriterFunction", "lambdas.heating_settings_writer.handler.lambda_handler", "Erfasst eine Heizungs-Einstellungsänderung")
        reader = make_function("ReaderFunction", "lambdas.heating_settings_reader.handler.lambda_handler", "Liest aktuelle Einstellungen und Historie")

        # Minimale Rechte pro Funktion
        parameter_table.grant(writer, "dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem")
        parameter_table.grant(reader, "dynamodb:Query")

        # --- API ---------------------------------------------------------
        api = apigw.HttpApi(
            self, "HttpApi",
            description="Heizung Einstellungen erfassen und lesen",
            create_default_stage=False,
            default_authorizer=authorizers.HttpIamAuthorizer(),
        )
        apigw.HttpStage(
            self, "DefaultStage",
            http_api=api,
            stage_name="$default",
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(rate_limit=5, burst_limit=10),
        )
        api.add_routes(
            path="/changes", methods=[apigw.HttpMethod.POST],
            integration=integrations.HttpLambdaIntegration("WriterIntegration", writer),
        )
        reader_integration = integrations.HttpLambdaIntegration("ReaderIntegration", reader)
        api.add_routes(path="/changes", methods=[apigw.HttpMethod.GET], integration=reader_integration)
        api.add_routes(path="/current", methods=[apigw.HttpMethod.GET], integration=reader_integration)

        CfnOutput(self, "ApiUrl", value=api.api_endpoint)
        CfnOutput(self, "ParameterTableName", value=parameter_table.table_name)
