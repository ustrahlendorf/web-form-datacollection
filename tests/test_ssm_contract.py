import pytest

from infrastructure.stacks.ssm_contract import (
    DEFAULT_SSM_NAMESPACE_PREFIX,
    ssm_parameter_arn,
    ssm_parameter_arn_from_segments,
    ssm_parameter_name,
)


def test_default_namespace_prefix_is_stable() -> None:
    assert DEFAULT_SSM_NAMESPACE_PREFIX == "/HeatingDataCollection"


@pytest.mark.parametrize(
    ("prefix", "segments", "expected"),
    [
        (
            DEFAULT_SSM_NAMESPACE_PREFIX,
            ("Submissions", "Active", "TableName"),
            f"{DEFAULT_SSM_NAMESPACE_PREFIX}/Submissions/Active/TableName",
        ),
        (
            DEFAULT_SSM_NAMESPACE_PREFIX.lstrip("/"),
            ("AutoRetrieval",),
            f"{DEFAULT_SSM_NAMESPACE_PREFIX}/AutoRetrieval",
        ),
        (
            f"{DEFAULT_SSM_NAMESPACE_PREFIX}/",
            ("Config", "SchemaVersion"),
            f"{DEFAULT_SSM_NAMESPACE_PREFIX}/Config/SchemaVersion",
        ),
    ],
)
def test_ssm_parameter_name_normalizes_prefix_and_segments(
    prefix: str,
    segments: tuple[str, ...],
    expected: str,
) -> None:
    assert ssm_parameter_name(prefix, *segments) == expected


def test_ssm_parameter_name_without_segments_returns_prefix() -> None:
    assert ssm_parameter_name(DEFAULT_SSM_NAMESPACE_PREFIX.lstrip("/")) == DEFAULT_SSM_NAMESPACE_PREFIX


def test_ssm_parameter_arn_uses_parameter_relative_path_format() -> None:
    parameter_name = ssm_parameter_name(
        DEFAULT_SSM_NAMESPACE_PREFIX, "AutoRetrieval", "ScheduleCron"
    )
    expected_relative_name = parameter_name.lstrip("/")
    arn = ssm_parameter_arn(
        region="eu-central-1",
        account="123456789012",
        parameter_name=parameter_name,
    )
    assert (
        arn
        == f"arn:aws:ssm:eu-central-1:123456789012:parameter/{expected_relative_name}"
    )


def test_ssm_parameter_arn_from_segments_builds_path_and_arn() -> None:
    arn = ssm_parameter_arn_from_segments(
        "eu-central-1",
        "123456789012",
        DEFAULT_SSM_NAMESPACE_PREFIX,
        *("AutoRetrieval", "*"),
    )
    expected_relative_name = ssm_parameter_name(
        DEFAULT_SSM_NAMESPACE_PREFIX, "AutoRetrieval", "*"
    ).lstrip("/")
    assert (
        arn
        == f"arn:aws:ssm:eu-central-1:123456789012:parameter/{expected_relative_name}"
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"region": "", "account": "123456789012", "parameter_name": "/A/B"},
        {"region": "eu-central-1", "account": "", "parameter_name": "/A/B"},
        {"region": "eu-central-1", "account": "123456789012", "parameter_name": "/"},
    ],
)
def test_ssm_parameter_arn_rejects_invalid_inputs(kwargs: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        ssm_parameter_arn(**kwargs)
