import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from infrastructure.stacks.heating_settings_stack import HeizungSettingsStack


def _template() -> Template:
    return Template.from_stack(HeizungSettingsStack(cdk.App(), "TestStack"))


def test_table_is_protected_and_on_demand():
    t = _template()
    t.resource_count_is("AWS::DynamoDB::GlobalTable", 1)
    t.has_resource_properties("AWS::DynamoDB::GlobalTable", {
        "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"},
                      {"AttributeName": "SK", "KeyType": "RANGE"}],
        # TableV2 setzt beides auf Replica-Ebene
        "Replicas": [Match.object_like({
            "DeletionProtectionEnabled": True,
            "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True},
        })],
    })
    for res in t.find_resources("AWS::DynamoDB::GlobalTable").values():
        assert res["DeletionPolicy"] == "Retain"


def test_parameter_table_has_fixed_name_and_same_keys():
    t = _template()
    t.has_resource_properties("AWS::DynamoDB::GlobalTable", {
        "TableName": "Settings-HeizungParameter",
        "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"},
                      {"AttributeName": "SK", "KeyType": "RANGE"}],
        "Replicas": [Match.object_like({
            "DeletionProtectionEnabled": True,
            "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True},
        })],
    })


def test_lambdas_use_parameter_table_only():
    t = _template()
    param_id = next(iter(t.find_resources(
        "AWS::DynamoDB::GlobalTable", {"Properties": {"TableName": "Settings-HeizungParameter"}})))
    for fn in t.find_resources("AWS::Lambda::Function").values():
        assert fn["Properties"]["Environment"]["Variables"]["TABLE_NAME"] == {"Ref": param_id}
    for pol in t.find_resources("AWS::IAM::Policy").values():
        for stmt in pol["Properties"]["PolicyDocument"]["Statement"]:
            assert param_id in str(stmt["Resource"]), "Rechte nur auf Parameter-Tabelle"


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
