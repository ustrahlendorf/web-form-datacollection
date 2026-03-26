"""Standard Lambda ``Code`` assets from the repository root."""

from __future__ import annotations

from aws_cdk import BundlingOptions, aws_lambda as lambda_

from infrastructure.config.lambda_assets import LAMBDA_CODE_ASSET_EXCLUDE
from infrastructure.config.paths import repo_root


def python_lambda_code_from_repo(*, bundling: BundlingOptions | None = None) -> lambda_.Code:
    """
    Asset bundle: entire repo root with shared excludes.

    Optional Docker ``bundling`` installs ``requirements-heating.txt`` and copies ``src`` + ``backend``.
    """
    kwargs: dict = {"exclude": list(LAMBDA_CODE_ASSET_EXCLUDE)}
    if bundling is not None:
        kwargs["bundling"] = bundling
    return lambda_.Code.from_asset(str(repo_root()), **kwargs)


def heating_lambda_bundling() -> BundlingOptions:
    """Bundling step shared by heating / Viessmann Lambdas (pip + copy ``src`` and ``backend``)."""
    return BundlingOptions(
        image=lambda_.Runtime.PYTHON_3_11.bundling_image,
        command=[
            "bash",
            "-c",
            "pip install -r /asset-input/requirements-heating.txt -t /asset-output "
            "&& cp -r /asset-input/src /asset-input/backend /asset-output/",
        ],
    )
