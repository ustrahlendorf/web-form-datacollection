#!/usr/bin/env python3
import aws_cdk as cdk

from heizung_settings_api.stack import HeizungSettingsStack

app = cdk.App()
HeizungSettingsStack(
    app, "HeizungSettingsStack",
    description="Heizung: Einstellungen per API erfassen (API Gateway, Lambda, DynamoDB)",
)
app.synth()
