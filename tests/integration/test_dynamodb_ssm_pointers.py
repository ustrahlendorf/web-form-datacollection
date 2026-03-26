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

from infrastructure.stacks.dynamodb_stack import DynamoDBStack
from infrastructure.stacks.ssm_contract import (
    DEFAULT_SSM_NAMESPACE_PREFIX,
    SUBMISSIONS_ACTIVE_TABLE_ARN_SEGMENTS,
    SUBMISSIONS_ACTIVE_TABLE_NAME_SEGMENTS,
    SUBMISSIONS_PASSIVE_TABLE_ARN_SEGMENTS,
    SUBMISSIONS_PASSIVE_TABLE_NAME_SEGMENTS,
    ssm_parameter_name,
)


def test_dynamodb_stack_writes_active_passive_ssm_pointers() -> None:
    app = App()

    env_config = Environment(account="123456789012", region="eu-central-1")

    stack = DynamoDBStack(
        app,
        "DynamoDbStackTest",
        environment_name="dev",
        active_submissions_table_name="submissions-active",
        passive_submissions_table_name="submissions-passive",
        env=env_config,
    )

    template = Template.from_stack(stack)

    template.resource_count_is("AWS::SSM::Parameter", 4)
    expected_prefix = DEFAULT_SSM_NAMESPACE_PREFIX

    for expected_name in (
        ssm_parameter_name(expected_prefix, *SUBMISSIONS_ACTIVE_TABLE_NAME_SEGMENTS),
        ssm_parameter_name(expected_prefix, *SUBMISSIONS_ACTIVE_TABLE_ARN_SEGMENTS),
        ssm_parameter_name(expected_prefix, *SUBMISSIONS_PASSIVE_TABLE_NAME_SEGMENTS),
        ssm_parameter_name(expected_prefix, *SUBMISSIONS_PASSIVE_TABLE_ARN_SEGMENTS),
    ):
        template.has_resource_properties(
            "AWS::SSM::Parameter",
            {
                "Name": expected_name,
                "Type": "String",
                "Value": Match.any_value(),
            },
        )


