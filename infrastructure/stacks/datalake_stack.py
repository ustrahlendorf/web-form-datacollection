"""
S3 DataLake stack for DynamoDB snapshot exports (dev).

This stack provisions a dedicated, private, versioned S3 bucket intended to
store monthly “snapshots” of the DynamoDB submissions table.

Design goals
------------
- One bucket for the dev environment across multiple years
- Athena/Glue-friendly partitioning via S3 prefixes (year=YYYY/month=MM/...)
- Secure defaults:
  - Block all public access
  - Server-side encryption
  - Enforce SSL
  - Versioning enabled (protect against accidental overwrite/deletion)

Notes
-----
- Bucket names must be globally unique. We include account + region to avoid
  collisions while keeping the required prefix `data-collection-`.
"""

from aws_cdk import (
    Stack,
    aws_s3 as s3,
    CfnOutput,
    RemovalPolicy,
)
from constructs import Construct


class DataLakeStack(Stack):
    """Stack for the dev DataLake S3 bucket used for DynamoDB exports."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment_name: str,
        **kwargs,
    ) -> None:
        """
        Initialize the DataLake stack.

        Args:
            scope: The parent construct
            construct_id: The logical ID of the stack
            environment_name: The environment name (dev, prod, etc.)
            **kwargs: Additional arguments to pass to Stack
        """
        super().__init__(scope, construct_id, **kwargs)
        self.environment_name = environment_name

        # Keep the bucket name deterministic but globally unique. Including account/region
        # makes collisions extremely unlikely while still starting with `data-collection-`.
        #
        # Note: `self.account`/`self.region` may be tokens at synth-time; CDK will resolve
        # them during deployment.
        bucket_name = f"data-collection-datalake-{environment_name}-{self.account}-{self.region}"

        datalake_bucket = s3.Bucket(
            self,
            "DataLakeBucket",
            bucket_name=bucket_name,
            versioned=True,
            block_public_access=s3.BlockPublicAccess(
                block_public_acls=True,
                block_public_policy=True,
                ignore_public_acls=True,
                restrict_public_buckets=True,
            ),
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            # This bucket is a long-lived archive for exports; do not delete automatically.
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.datalake_bucket = datalake_bucket

        CfnOutput(
            self,
            "DataLakeBucketName",
            value=datalake_bucket.bucket_name,
            export_name=f"DataCollectionDataLakeBucketName-{environment_name}",
            description="S3 bucket name for dev DataLake DynamoDB exports",
        )

        CfnOutput(
            self,
            "DataLakeBucketArn",
            value=datalake_bucket.bucket_arn,
            export_name=f"DataCollectionDataLakeBucketArn-{environment_name}",
            description="S3 bucket ARN for dev DataLake DynamoDB exports",
        )


