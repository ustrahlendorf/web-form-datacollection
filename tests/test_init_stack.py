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
from infrastructure.stacks.ssm_contract import DEFAULT_SSM_NAMESPACE_PREFIX, ssm_parameter_name


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

    template.resource_count_is("AWS::SSM::Parameter", 9)
    expected_prefix = DEFAULT_SSM_NAMESPACE_PREFIX

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": ssm_parameter_name(expected_prefix, "Config", "SchemaVersion"),
            "Type": "String",
            "Value": "1",
        },
    )

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": ssm_parameter_name(expected_prefix, "FeatureFlags", "EnablePassiveReads"),
            "Type": "String",
            "Value": "false",
        },
    )

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": ssm_parameter_name(
                expected_prefix, "Operations", "Rollover", "RunbookVersion"
            ),
            "Type": "String",
            "Value": "2026-01",
        },
    )

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": ssm_parameter_name(expected_prefix, "AutoRetrieval", "ScheduleCron"),
            "Type": "String",
            "Value": "0 6 * * ? *",
        },
    )

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": ssm_parameter_name(expected_prefix, "AutoRetrieval", "MaxRetries"),
            "Type": "String",
            "Value": "5",
            "Description": "Migration-only SSM fallback for max retry attempts (runtime source is AppConfig).",
        },
    )

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": ssm_parameter_name(
                expected_prefix, "AutoRetrieval", "FrequentScheduleCron"
            ),
            "Type": "String",
            "Value": "0/15 * * * ? *",
        },
    )

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": ssm_parameter_name(
                expected_prefix, "AutoRetrieval", "FrequentActiveWindows"
            ),
            "Type": "String",
            "Value": '[{"start":"00:00","stop":"24:00"}]',
        },
    )

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": ssm_parameter_name(
                expected_prefix, "AutoRetrieval", "RetryDelaySeconds"
            ),
            "Type": "String",
            "Value": "300",
            "Description": "Migration-only SSM fallback for retry delay seconds (runtime source is AppConfig).",
        },
    )

    template.has_resource_properties(
        "AWS::SSM::Parameter",
        {
            "Name": ssm_parameter_name(expected_prefix, "AutoRetrieval", "UserId"),
            "Type": "String",
            "Value": "SET_ME",
            "Description": (
                "Migration-only SSM fallback for installation owner user_id (runtime source is AppConfig). "
                "Update only during cutover troubleshooting."
            ),
        },
    )


