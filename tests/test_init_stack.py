import os
from pathlib import Path

# CDK/jsii tries to write to the user cache directory (e.g. ~/Library/Caches/...)
# during import. In the sandbox, writes outside the workspace are blocked, so we
# redirect the jsii runtime package cache into the repo.
os.environ.setdefault(
    "JSII_RUNTIME_PACKAGE_CACHE_ROOT",
    str(Path(__file__).resolve().parent.parent / ".jsii-package-cache"),
)

from aws_cdk import App, Environment
from aws_cdk.assertions import Template

from infrastructure.stacks.init_stack import InitStack


def test_init_stack_creates_static_ssm_parameters() -> None:
    app = App()

    # Environment values do not impact the SSM parameter names (single-environment namespace),
    # but CDK stacks typically receive an explicit env in this repo.
    env_config = Environment(account="123456789012", region="eu-central-1")

    stack = InitStack(
        app,
        "InitStackTest",
        environment_name="dev",
        env=env_config,
    )

    template = Template.from_stack(stack)

    template.resource_count_is("AWS::SSM::Parameter", 7)

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": "/HeatingDataCollection/Config/SchemaVersion",
            "Type": "String",
            "Value": "1",
        },
    )

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": "/HeatingDataCollection/FeatureFlags/EnablePassiveReads",
            "Type": "String",
            "Value": "false",
        },
    )

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": "/HeatingDataCollection/Operations/Rollover/RunbookVersion",
            "Type": "String",
            "Value": "2026-01",
        },
    )

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": "/HeatingDataCollection/AutoRetrieval/ScheduleCron",
            "Type": "String",
            "Value": "0 6 * * ? *",
        },
    )

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": "/HeatingDataCollection/AutoRetrieval/MaxRetries",
            "Type": "String",
            "Value": "5",
        },
    )

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": "/HeatingDataCollection/AutoRetrieval/RetryDelaySeconds",
            "Type": "String",
            "Value": "300",
        },
    )

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": "/HeatingDataCollection/AutoRetrieval/UserId",
            "Type": "String",
            "Value": "SET_ME",
        },
    )


