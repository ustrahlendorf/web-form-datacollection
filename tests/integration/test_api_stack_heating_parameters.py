import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from infrastructure.stacks.api_stack import APIStack


def _template() -> Template:
    stack = APIStack(
        cdk.App(), "TestApi",
        environment_name="dev",
        cognito_user_pool_id="eu-central-1_TEST",
        cognito_user_pool_client_id="client",
        appconfig_application_id="app",
        appconfig_environment_id="env",
        appconfig_profile_id="prof",
        appconfig_deployment_strategy_id="strat",
        env=cdk.Environment(account="123456789012", region="eu-central-1"),
    )
    return Template.from_stack(stack)


def _function_id(t: Template) -> str:
    fns = t.find_resources("AWS::Lambda::Function", {
        "Properties": {"Handler": "lambdas.heating_parameters.handler.lambda_handler"}})
    assert len(fns) == 1
    return next(iter(fns))


def test_route_is_jwt_protected_get():
    t = _template()
    t.has_resource_properties("AWS::ApiGatewayV2::Route", {
        "RouteKey": "GET /heating/parameters",
        "AuthorizationType": "JWT",
        "AuthorizerId": Match.any_value(),
    })


def test_function_env_points_to_parameter_table():
    t = _template()
    t.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "lambdas.heating_parameters.handler.lambda_handler",
        "Environment": {"Variables": Match.object_like({
            "TABLE_NAME": "Settings-HeizungParameter", "SYSTEM_ID": "haus"})},
    })


def test_function_has_own_role_with_query_only_on_parameter_table():
    t = _template()
    fn_id = _function_id(t)
    role_ref = t.find_resources("AWS::Lambda::Function")[fn_id]["Properties"]["Role"]["Fn::GetAtt"][0]
    shared = t.find_resources("AWS::IAM::Role", {"Properties": {"RoleName": "data-collection-lambda-role-dev"}})
    assert role_ref not in shared, "eigene Rolle, nicht die geteilte Lambda-Rolle"
    own = [p["Properties"]["PolicyDocument"]["Statement"]
           for p in t.find_resources("AWS::IAM::Policy").values()
           if any(r.get("Ref") == role_ref for r in p["Properties"]["Roles"])]
    stmts = [s for group in own for s in group]
    assert len(stmts) == 1
    assert stmts[0]["Action"] == "dynamodb:Query"
    assert stmts[0]["Effect"] == "Allow"
    assert "table/Settings-HeizungParameter" in str(stmts[0]["Resource"])
    assert "*" not in str(stmts[0]["Resource"]).replace("AWS::", "")


WRITER_HANDLER = "lambdas.heating_parameters_writer.handler.lambda_handler"


def test_post_route_is_jwt_protected():
    t = _template()
    t.has_resource_properties("AWS::ApiGatewayV2::Route", {
        "RouteKey": "POST /heating/parameters",
        "AuthorizationType": "JWT",
        "AuthorizerId": Match.any_value(),
    })


def test_writer_function_env_points_to_parameter_table():
    t = _template()
    t.has_resource_properties("AWS::Lambda::Function", {
        "Handler": WRITER_HANDLER,
        "Environment": {"Variables": Match.object_like({
            "TABLE_NAME": "Settings-HeizungParameter", "SYSTEM_ID": "haus",
            "PYTHONPATH": Match.any_value()})},
    })


def test_writer_has_own_role_with_get_query_put_only_on_parameter_table():
    t = _template()
    fns = t.find_resources("AWS::Lambda::Function", {"Properties": {"Handler": WRITER_HANDLER}})
    assert len(fns) == 1
    role_ref = next(iter(fns.values()))["Properties"]["Role"]["Fn::GetAtt"][0]
    shared = t.find_resources("AWS::IAM::Role", {"Properties": {"RoleName": "data-collection-lambda-role-dev"}})
    assert role_ref not in shared, "eigene Rolle, nicht die geteilte Lambda-Rolle"
    stmts = [s for p in t.find_resources("AWS::IAM::Policy").values()
             if any(r.get("Ref") == role_ref for r in p["Properties"]["Roles"])
             for s in p["Properties"]["PolicyDocument"]["Statement"]]
    assert len(stmts) == 1
    assert stmts[0]["Effect"] == "Allow"
    assert sorted(stmts[0]["Action"]) == ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"]
    assert "table/Settings-HeizungParameter" in str(stmts[0]["Resource"])
    assert "*" not in str(stmts[0]["Resource"]).replace("AWS::", "")


# --- Viessmann-Anbindung (Secret gesetzt) ---------------------------------------------------

SECRET_ARN = "arn:aws:secretsmanager:eu-central-1:123456789012:secret:viessmann-AbCdEf"
LIVE_HANDLER = "lambdas.heating_parameters_live.handler.lambda_handler"


def _template_with_secret(context=None) -> Template:
    stack = APIStack(
        cdk.App(context={"aws:cdk:bundling-stacks": [], **(context or {})}), "TestApiSecret",
        environment_name="dev",
        cognito_user_pool_id="eu-central-1_TEST",
        cognito_user_pool_client_id="client",
        appconfig_application_id="app",
        appconfig_environment_id="env",
        appconfig_profile_id="prof",
        appconfig_deployment_strategy_id="strat",
        viessmann_credentials_secret_arn=SECRET_ARN,
        env=cdk.Environment(account="123456789012", region="eu-central-1"),
    )
    return Template.from_stack(stack)


def _own_statements(t: Template, handler: str) -> list:
    fns = t.find_resources("AWS::Lambda::Function", {"Properties": {"Handler": handler}})
    assert len(fns) == 1
    role_ref = next(iter(fns.values()))["Properties"]["Role"]["Fn::GetAtt"][0]
    return [s for p in t.find_resources("AWS::IAM::Policy").values()
            if any(r.get("Ref") == role_ref for r in p["Properties"]["Roles"])
            for s in p["Properties"]["PolicyDocument"]["Statement"]]


def test_live_and_sync_routes_are_jwt_protected():
    t = _template_with_secret()
    for key in ("GET /heating/parameters/live", "POST /heating/parameters/sync"):
        t.has_resource_properties("AWS::ApiGatewayV2::Route", {
            "RouteKey": key, "AuthorizationType": "JWT", "AuthorizerId": Match.any_value()})


def test_live_routes_absent_without_secret():
    t = _template()
    t.resource_count_is("AWS::ApiGatewayV2::Route", len(t.find_resources("AWS::ApiGatewayV2::Route")))
    keys = [r["Properties"]["RouteKey"] for r in t.find_resources("AWS::ApiGatewayV2::Route").values()]
    assert "GET /heating/parameters/live" not in keys


def test_writer_gets_secret_env_timeout_and_secret_access():
    t = _template_with_secret()
    t.has_resource_properties("AWS::Lambda::Function", {
        "Handler": WRITER_HANDLER, "Timeout": 29,
        "Environment": {"Variables": Match.object_like({
            "VIESSMANN_CREDENTIALS_SECRET_ARN": SECRET_ARN,
            "VIESSMANN_TOKEN_CACHE_PATH": "/tmp/viessmann/tokens.json",
            "PYTHONPATH": Match.any_value()})},
    })
    stmts = _own_statements(t, WRITER_HANDLER)
    secret = [s for s in stmts if s["Action"] == "secretsmanager:GetSecretValue"]
    assert len(secret) == 1 and secret[0]["Resource"] == SECRET_ARN


def test_live_function_has_only_needed_permissions():
    t = _template_with_secret()
    t.has_resource_properties("AWS::Lambda::Function", {
        "Handler": LIVE_HANDLER, "Timeout": 29,
        "Environment": {"Variables": Match.object_like({
            "TABLE_NAME": "Settings-HeizungParameter",
            "VIESSMANN_CREDENTIALS_SECRET_ARN": SECRET_ARN})},
    })
    stmts = _own_statements(t, LIVE_HANDLER)
    actions = sorted(a for s in stmts for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"]))
    assert actions == ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query",
                       "secretsmanager:GetSecretValue"]
    assert all("*" not in str(s["Resource"]).replace("AWS::", "") for s in stmts)
