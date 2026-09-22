"""
MedBridge CDK Stack
Copy this to: medbridge/medbridge/medbridge_stack.py
"""

from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_iam as iam,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
)
from constructs import Construct


class MedbridgeStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ===================================================
        # 1. DynamoDB Table — Health Facilities
        # ===================================================
        facilities_table = dynamodb.Table(
            self, "HealthFacilities",
            table_name="medbridge-facilities",
            partition_key=dynamodb.Attribute(
                name="facility_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # GSI for querying by state + district
        facilities_table.add_global_secondary_index(
            index_name="state-district-index",
            partition_key=dynamodb.Attribute(
                name="state",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="district",
                type=dynamodb.AttributeType.STRING
            ),
        )

        # ===================================================
        # 2. DynamoDB Table — Triage History (optional)
        # ===================================================
        triage_table = dynamodb.Table(
            self, "TriageHistory",
            table_name="medbridge-triage-history",
            partition_key=dynamodb.Attribute(
                name="session_id",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ===================================================
        # 3. Lambda — Symptom Triage (Bedrock)
        # ===================================================
        triage_lambda = _lambda.Function(
            self, "SymptomTriageFn",
            function_name="medbridge-symptom-triage",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=_lambda.Code.from_asset("lambda/symptom_triage"),
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "TRIAGE_TABLE": triage_table.table_name,
                "MODEL_ID": "anthropic.claude-3-5-sonnet-20241022-v2:0",
            },
        )

        # Grant Bedrock access
        triage_lambda.add_to_role_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
            ],
            resources=["arn:aws:bedrock:ap-south-1::foundation-model/*"],
        ))
        triage_table.grant_write_data(triage_lambda)

        # ===================================================
        # 4. Lambda — Clinic Finder
        # ===================================================
        clinic_finder_lambda = _lambda.Function(
            self, "ClinicFinderFn",
            function_name="medbridge-clinic-finder",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=_lambda.Code.from_asset("lambda/clinic_finder"),
            timeout=Duration.seconds(15),
            memory_size=256,
            environment={
                "FACILITIES_TABLE": facilities_table.table_name,
            },
        )
        facilities_table.grant_read_data(clinic_finder_lambda)

        # ===================================================
        # 5. Lambda — Health Info Cards
        # ===================================================
        health_info_lambda = _lambda.Function(
            self, "HealthInfoFn",
            function_name="medbridge-health-info",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=_lambda.Code.from_asset("lambda/health_info"),
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "MODEL_ID": "anthropic.claude-3-5-sonnet-20241022-v2:0",
            },
        )

        health_info_lambda.add_to_role_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["bedrock:InvokeModel"],
            resources=["arn:aws:bedrock:ap-south-1::foundation-model/*"],
        ))

        # ===================================================
        # 6. API Gateway — REST API
        # ===================================================
        api = apigw.RestApi(
            self, "MedBridgeApi",
            rest_api_name="MedBridge API",
            description="MedBridge — Rural Health Clinic Finder & Symptom Triage",
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "Authorization"],
            ),
        )

        # /triage — POST
        triage_resource = api.root.add_resource("triage")
        triage_resource.add_method(
            "POST",
            apigw.LambdaIntegration(triage_lambda),
        )

        # /clinics — GET ?lat=xx&lng=xx&radius=xx
        clinics_resource = api.root.add_resource("clinics")
        clinics_resource.add_method(
            "GET",
            apigw.LambdaIntegration(clinic_finder_lambda),
        )

        # /health-info — POST
        health_info_resource = api.root.add_resource("health-info")
        health_info_resource.add_method(
            "POST",
            apigw.LambdaIntegration(health_info_lambda),
        )

        # ===================================================
        # 7. S3 + CloudFront — Frontend Hosting
        # ===================================================
        frontend_bucket = s3.Bucket(
            self, "FrontendBucket",
            bucket_name=f"medbridge-frontend-{self.account}",
            website_index_document="index.html",
            website_error_document="index.html",
            public_read_access=False,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # CloudFront OAI
        oai = cloudfront.OriginAccessIdentity(self, "OAI")
        frontend_bucket.grant_read(oai)

        # CloudFront Distribution
        distribution = cloudfront.Distribution(
            self, "FrontendDist",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3Origin(
                    frontend_bucket,
                    origin_access_identity=oai,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                ),
            ],
        )

        # ===================================================
        # 8. Outputs
        # ===================================================
        CfnOutput(self, "ApiUrl",
            value=api.url,
            description="MedBridge API Gateway URL",
        )
        CfnOutput(self, "CloudFrontUrl",
            value=f"https://{distribution.distribution_domain_name}",
            description="MedBridge Frontend URL (public)",
        )
        CfnOutput(self, "FrontendBucketName",
            value=frontend_bucket.bucket_name,
            description="S3 bucket for frontend deployment",
        )
