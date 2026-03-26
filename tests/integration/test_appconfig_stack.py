import os
from pathlib import Path

# CDK/jsii tries to write to the user cache directory (e.g. ~/Library/Caches/...)
# during import. In the sandbox, writes outside the workspace are blocked, so we
# redirect the jsii runtime package cache into the repo.
os.environ.setdefault(
    "JSII_RUNTIME_PACKAGE_CACHE_ROOT",
    str(Path(__file__).resolve().parent.parent.parent / ".jsii-package-cache"),
)

from aws_cdk import App, Environment
from aws_cdk.assertions import Match, Template

from infrastructure.stacks.appconfig_stack import AppConfigStack


def test_appconfig_stack_creates_application_environment_profile_and_validators() -> None:
    app = App()
    env_config = Environment(account="123456789012", region="eu-central-1")

    stack = AppConfigStack(
        app,
        "AppConfigStackTest",
        environment_name="dev",
        env=env_config,
    )
    template = Template.from_stack(stack)

    template.resource_count_is("AWS::AppConfig::Application", 1)
    template.resource_count_is("AWS::AppConfig::Environment", 1)
    template.resource_count_is("AWS::AppConfig::ConfigurationProfile", 1)
    template.resource_count_is("AWS::AppConfig::DeploymentStrategy", 1)
    template.resource_count_is("AWS::Lambda::Function", 1)
    template.resource_count_is("AWS::Lambda::Permission", 1)

    template.has_resource_properties(
        "AWS::AppConfig::Application",
        {"Name": "HeatingDataCollection"},
    )
    template.has_resource_properties(
        "AWS::AppConfig::Environment",
        {"Name": "dev"},
    )
    template.has_resource_properties(
        "AWS::AppConfig::ConfigurationProfile",
        {
            "Name": "auto-retrieval",
            "LocationUri": "hosted",
            "Type": "AWS.Freeform",
            "Validators": Match.array_with(
                [
                    Match.object_like({"Type": "JSON_SCHEMA"}),
                    Match.object_like({"Type": "LAMBDA"}),
                ]
            ),
        },
    )
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Handler": "src.handlers.auto_retrieval_config_validator.lambda_handler",
            "Runtime": "python3.11",
            "Timeout": 10,
        },
    )
    template.has_resource_properties(
        "AWS::AppConfig::ConfigurationProfile",
        {
            "Validators": Match.array_with(
                [
                    Match.object_like(
                        {
                            "Type": "JSON_SCHEMA",
                            "Content": Match.string_like_regexp('"schemaVersion"'),
                        }
                    ),
                    Match.object_like({"Type": "LAMBDA"}),
                ]
            )
        },
    )
    template.has_resource_properties(
        "AWS::AppConfig::DeploymentStrategy",
        {
            "DeploymentDurationInMinutes": 0,
            "FinalBakeTimeInMinutes": 0,
            "GrowthFactor": 100,
            "ReplicateTo": "NONE",
        },
    )
