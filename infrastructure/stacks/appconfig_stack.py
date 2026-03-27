"""AppConfig stack for runtime auto-retrieval configuration."""

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_appconfig as appconfig,
    aws_lambda as lambda_,
)
from constructs import Construct

from infrastructure.cdk_constructs.python_lambda_asset import python_lambda_code_from_repo


class AppConfigStack(Stack):
    """Stack that provisions AppConfig resources for auto-retrieval runtime config."""

    APPLICATION_NAME = "HeatingDataCollection"
    PROFILE_NAME = "auto-retrieval"

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.environment_name = environment_name

        validator_fn = lambda_.Function(
            self,
            "AutoRetrievalConfigValidatorFunction",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="lambdas.auto_retrieval_config_validator.handler.lambda_handler",
            code=python_lambda_code_from_repo(),
            timeout=Duration.seconds(10),
            memory_size=128,
            description="Validates AppConfig auto-retrieval documents.",
        )
        lambda_.CfnPermission(
            self,
            "AllowAppConfigInvokeValidator",
            action="lambda:InvokeFunction",
            function_name=validator_fn.function_name,
            principal="appconfig.amazonaws.com",
        )

        self.appconfig_application = appconfig.CfnApplication(
            self,
            "AutoRetrievalAppConfigApplication",
            name=self.APPLICATION_NAME,
            description="Runtime dynamic configuration for heating data auto-retrieval.",
        )

        self.appconfig_environment = appconfig.CfnEnvironment(
            self,
            "AutoRetrievalAppConfigEnvironment",
            application_id=self.appconfig_application.ref,
            name=self.environment_name,
            description=f"{self.environment_name} environment for auto-retrieval runtime config.",
        )

        self.deployment_strategy = appconfig.CfnDeploymentStrategy(
            self,
            "AutoRetrievalImmediateDeploymentStrategy",
            name=f"auto-retrieval-immediate-{self.environment_name}",
            deployment_duration_in_minutes=0,
            growth_factor=100,
            final_bake_time_in_minutes=0,
            replicate_to="NONE",
            description="Immediate rollout strategy for auto-retrieval config updates.",
        )

        self.appconfig_profile = appconfig.CfnConfigurationProfile(
            self,
            "AutoRetrievalHostedConfigurationProfile",
            application_id=self.appconfig_application.ref,
            name=self.PROFILE_NAME,
            location_uri="hosted",
            type="AWS.Freeform",
            description="Hosted AppConfig profile for auto-retrieval settings.",
            validators=[
                appconfig.CfnConfigurationProfile.ValidatorsProperty(
                    type="JSON_SCHEMA",
                    content=self._json_schema_validator(),
                ),
                appconfig.CfnConfigurationProfile.ValidatorsProperty(
                    type="LAMBDA",
                    content=validator_fn.function_arn,
                ),
            ],
        )
        self.appconfig_profile.node.add_dependency(validator_fn)

        CfnOutput(
            self,
            "AppConfigApplicationId",
            value=self.appconfig_application.ref,
            description="AppConfig application id for auto-retrieval config.",
        )
        CfnOutput(
            self,
            "AppConfigEnvironmentId",
            value=self.appconfig_environment.ref,
            description="AppConfig environment id for auto-retrieval config.",
        )
        CfnOutput(
            self,
            "AppConfigProfileId",
            value=self.appconfig_profile.ref,
            description="AppConfig configuration profile id for auto-retrieval config.",
        )
        CfnOutput(
            self,
            "AppConfigDeploymentStrategyId",
            value=self.deployment_strategy.ref,
            description="AppConfig deployment strategy id for auto-retrieval config.",
        )

    @staticmethod
    def _json_schema_validator() -> str:
        return """{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "frequentActiveWindows",
    "maxRetries",
    "retryDelaySeconds",
    "userId",
    "schemaVersion"
  ],
  "properties": {
    "schemaVersion": { "type": "integer", "const": 1 },
    "maxRetries": { "type": "integer", "minimum": 0, "maximum": 20 },
    "retryDelaySeconds": { "type": "integer", "minimum": 1, "maximum": 3600 },
    "userId": { "type": "string", "minLength": 1 },
    "frequentActiveWindows": {
      "type": "array",
      "minItems": 1,
      "maxItems": 5,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["start", "stop"],
        "properties": {
          "start": {
            "type": "string",
            "pattern": "^([01][0-9]|2[0-4]):[0-5][0-9]$"
          },
          "stop": {
            "type": "string",
            "pattern": "^([01][0-9]|2[0-4]):[0-5][0-9]$"
          }
        }
      }
    }
  }
}"""
