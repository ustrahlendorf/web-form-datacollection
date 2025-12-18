# Data Collection Web Application - Infrastructure Package
#
# Intentionally avoid importing the CDK app (or stacks) at package import time.
# CDK executes `infrastructure/app.py` directly (see `cdk.json`), so importing
# here only increases the risk of circular imports and synthesis failures.

__all__ = []
