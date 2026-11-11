import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from heizung_settings_api.stack import HeizungSettingsStack


def _template() -> Template:
    return Template.from_stack(HeizungSettingsStack(cdk.App(), "TestStack"))


def test_table_is_protected_and_on_demand():
    _template().has_resource_properties("AWS::DynamoDB::GlobalTable", {
        "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"},
                      {"AttributeName": "SK", "KeyType": "RANGE"}],
        # TableV2 setzt beides auf Replica-Ebene
        "Replicas": [Match.object_like({
            "DeletionProtectionEnabled": True,
            "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True},
        })],
    })
    _template().has_resource("AWS::DynamoDB::GlobalTable", {"DeletionPolicy": "Retain"})


def test_two_arm_lambdas():
    t = _template()
    t.resource_count_is("AWS::Lambda::Function", 2)
    t.has_resource_properties("AWS::Lambda::Function", {"Architectures": ["arm64"], "Runtime": "python3.13"})


def test_all_routes_require_iam_auth():
    t = _template()
    routes = t.find_resources("AWS::ApiGatewayV2::Route")
    assert len(routes) == 3
    assert all(r["Properties"]["AuthorizationType"] == "AWS_IAM" for r in routes.values())


def test_lambda_permissions_are_least_privilege():
    t = _template()
    policies = t.find_resources("AWS::IAM::Policy")
    actions = set()
    for p in policies.values():
        for stmt in p["Properties"]["PolicyDocument"]["Statement"]:
            acts = stmt["Action"] if isinstance(stmt["Action"], list) else [stmt["Action"]]
            actions.update(acts)
    assert actions == {"dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"}
