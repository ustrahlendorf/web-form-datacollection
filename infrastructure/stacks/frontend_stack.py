"""S3 and CloudFront stack for frontend hosting."""

from aws_cdk import (
    Stack,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3_deployment as s3_deployment,
    CfnOutput,
    RemovalPolicy,
    Duration,
)
from constructs import Construct


class FrontendStack(Stack):
    """Stack for S3 bucket and CloudFront distribution."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment_name: str,
        **kwargs
    ) -> None:
        """
        Initialize the frontend stack.

        Args:
            scope: The parent construct
            construct_id: The logical ID of the stack
            environment_name: The environment name (dev, prod, etc.)
            **kwargs: Additional arguments to pass to Stack
        """
        super().__init__(scope, construct_id, **kwargs)
        self.environment_name = environment_name

        # Create S3 bucket for static website hosting
        frontend_bucket = s3.Bucket(
            self,
            "FrontendBucket",
            bucket_name=f"data-collection-frontend-{environment_name}",
            versioned=True,
            block_public_access=s3.BlockPublicAccess(
                block_public_acls=True,
                block_public_policy=True,
                ignore_public_acls=True,
                restrict_public_buckets=True,
            ),
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Create Origin Access Identity for CloudFront to access S3
        oai = cloudfront.OriginAccessIdentity(
            self,
            "FrontendOAI",
            comment=f"OAI for Data Collection Frontend {environment_name}",
        )

        # Grant CloudFront read access to S3 bucket
        frontend_bucket.grant_read(oai)

        # Create CloudFront logs bucket with ACL enabled
        logs_bucket = s3.Bucket(
            self,
            "CloudFrontLogsBucket",
            bucket_name=f"data-collection-cf-logs-{environment_name}",
            block_public_access=s3.BlockPublicAccess(
                block_public_acls=True,
                block_public_policy=True,
                ignore_public_acls=True,
                restrict_public_buckets=True,
            ),
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
        )

        # Create CloudFront distribution
        distribution = cloudfront.Distribution(
            self,
            "FrontendDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3Origin(
                    frontend_bucket,
                    origin_access_identity=oai,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                compress=True,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.minutes(5),
                ),
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.minutes(5),
                ),
            ],
            enable_logging=True,
            log_bucket=logs_bucket,
            log_file_prefix="cloudfront-logs/",
        )

        # Store references
        self.frontend_bucket = frontend_bucket
        self.distribution = distribution

        # Export CloudFront domain name
        CfnOutput(
            self,
            "CloudFrontDomainName",
            value=distribution.domain_name,
            export_name=f"DataCollectionCloudFrontDomain-{environment_name}",
            description="CloudFront distribution domain name",
        )

        # Export S3 bucket name
        CfnOutput(
            self,
            "FrontendBucketName",
            value=frontend_bucket.bucket_name,
            export_name=f"DataCollectionFrontendBucket-{environment_name}",
            description="S3 bucket name for frontend assets",
        )

        # Export CloudFront distribution ID
        CfnOutput(
            self,
            "CloudFrontDistributionId",
            value=distribution.distribution_id,
            export_name=f"DataCollectionCloudFrontDistributionId-{environment_name}",
            description="CloudFront distribution ID for cache invalidation",
        )
