# Approval console: Cognito sign-in -> API Gateway HTTP API (JWT authorizer) -> Lambda -> Aurora Data API +
# Step Functions task token. The page itself is viewer/console.html on the existing CloudFront site.

terraform {
  required_providers {
    aws     = { source = "hashicorp/aws" }
    archive = { source = "hashicorp/archive" }
  }
}

variable "name" { type = string }
variable "prefix" { type = string }
variable "boundary_arn" { type = string }
variable "site_url" { type = string }
variable "db_cluster_arn" { type = string }
variable "db_secret_arn" { type = string }
variable "db_name" { type = string }
variable "approval_state_machine_arn" { type = string }
variable "artifacts_bucket" { type = string }
variable "source_file" { type = string }

data "aws_region" "current" {}

# ---------------------------------------------------------------- sign-in
resource "aws_cognito_user_pool" "this" {
  name                     = "${var.name}-console"
  deletion_protection      = "INACTIVE"
  mfa_configuration        = "OFF"
  auto_verified_attributes = []
  admin_create_user_config {
    allow_admin_create_user_only = true # no self sign-up: engineers are created by the administrator
  }
  password_policy {
    minimum_length    = 14
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = false
  }
}

resource "aws_cognito_user_pool_domain" "this" {
  domain       = var.prefix
  user_pool_id = aws_cognito_user_pool.this.id
}

resource "aws_cognito_user_pool_client" "web" {
  name                                 = "${var.name}-console-web"
  user_pool_id                         = aws_cognito_user_pool.this.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid"]
  callback_urls                        = ["${var.site_url}/console.html"]
  logout_urls                          = ["${var.site_url}/console.html"]
  supported_identity_providers         = ["COGNITO"]
  explicit_auth_flows                  = ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"]
  access_token_validity                = 1
  id_token_validity                    = 1
  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}

# ---------------------------------------------------------------- Lambda
data "archive_file" "lambda" {
  type        = "zip"
  source_file = var.source_file
  output_path = "${path.module}/.build/console.zip"
}

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name                 = "${var.name}-console-api"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  permissions_boundary = var.boundary_arn
}

data "aws_iam_policy_document" "lambda" {
  statement {
    actions   = ["rds-data:ExecuteStatement"]
    resources = [var.db_cluster_arn]
  }
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.db_secret_arn]
  }
  statement {
    actions   = ["states:SendTaskSuccess", "states:SendTaskFailure"]
    resources = [var.approval_state_machine_arn]
  }
  statement {
    actions   = ["s3:GetObject"]
    resources = ["arn:aws:s3:::${var.artifacts_bucket}/workorders/*"]
  }
  statement {
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${var.name}-console-api"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.name}-console-api"
  retention_in_days = 14
}

resource "aws_lambda_function" "api" {
  function_name    = "${var.name}-console-api"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "console.handler"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  timeout          = 30
  memory_size      = 256
  environment {
    variables = {
      DB_CLUSTER_ARN   = var.db_cluster_arn
      DB_SECRET_ARN    = var.db_secret_arn
      DB_NAME          = var.db_name
      ARTIFACTS_BUCKET = var.artifacts_bucket
    }
  }
  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy.lambda]
}

# ---------------------------------------------------------------- HTTP API
resource "aws_apigatewayv2_api" "this" {
  name          = "${var.name}-console"
  protocol_type = "HTTP"
  cors_configuration {
    allow_origins = [var.site_url]
    allow_methods = ["GET", "POST"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 3600
  }
}

resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id           = aws_apigatewayv2_api.this.id
  name             = "cognito"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  jwt_configuration {
    audience = [aws_cognito_user_pool_client.web.id]
    issuer   = "https://cognito-idp.${data.aws_region.current.region}.amazonaws.com/${aws_cognito_user_pool.this.id}"
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "routes" {
  for_each           = toset(["GET /packages", "GET /packages/{id}", "POST /packages/{id}/decision"])
  api_id             = aws_apigatewayv2_api.this.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }
}

resource "aws_lambda_permission" "api" {
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

output "api_url" { value = aws_apigatewayv2_api.this.api_endpoint }
output "user_pool_id" { value = aws_cognito_user_pool.this.id }
output "client_id" { value = aws_cognito_user_pool_client.web.id }
output "auth_domain" { value = "https://${aws_cognito_user_pool_domain.this.domain}.auth.${data.aws_region.current.region}.amazoncognito.com" }
