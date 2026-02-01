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

from infrastructure.stacks.cognito_stack import CognitoStack


def test_cognito_user_pool_disables_self_signup() -> None:
    """
    Self-signup MUST be disabled so only admins can create/invite users.

    CDK represents this in CloudFormation via:
    AdminCreateUserConfig.AllowAdminCreateUserOnly = True
    """
    app = App()
    env_config = Environment(account="123456789012", region="eu-central-1")

    stack = CognitoStack(
        app,
        "CognitoStackTest",
        environment_name="dev",
        env=env_config,
    )

    template = Template.from_stack(stack)

    template.resource_count_is("AWS::Cognito::UserPool", 1)
    template.has_resource_properties(
        "AWS::Cognito::UserPool",
        {
            "AdminCreateUserConfig": {
                "AllowAdminCreateUserOnly": True,
            }
        },
    )




