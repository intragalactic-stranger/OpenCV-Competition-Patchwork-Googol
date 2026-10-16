# The Ward Engineer's Assistant hosted on Amazon Bedrock AgentCore Runtime (container, arm64, IAM-authenticated).
# Same code as `python -m patchwork.agent.run`; the container is docker/agent.Dockerfile.

variable "name" { type = string }
variable "boundary_arn" { type = string }
variable "db_cluster_arn" { type = string }
variable "db_secret_arn" { type = string }
variable "db_name" { type = string }
variable "approval_state_machine_arn" { type = string }
variable "artifacts_bucket" { type = string }
variable "image_tag" {
  description = "Tag of the pushed agent image; the runtime is created only once an image exists"
  type        = string
  default     = ""
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

resource "aws_ecr_repository" "agent" {
  name                 = "${var.name}-agent"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}

resource "aws_ecr_lifecycle_policy" "agent" {
  repository = aws_ecr_repository.agent.name
  policy = jsonencode({ rules = [{ rulePriority = 1, description = "keep 5",
  selection = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }, action = { type = "expire" } }] })
}

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "runtime" {
  name                 = "${var.name}-agent-runtime"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  permissions_boundary = var.boundary_arn
}

data "aws_iam_policy_document" "runtime" {
  statement {
    sid     = "AmazonNovaOnly"
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [
      "arn:aws:bedrock:*::foundation-model/amazon.nova-*",
      "arn:aws:bedrock:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:inference-profile/apac.amazon.nova-*",
    ]
  }
  statement {
    sid       = "Register"
    actions   = ["rds-data:ExecuteStatement", "rds-data:BeginTransaction", "rds-data:CommitTransaction", "rds-data:RollbackTransaction"]
    resources = [var.db_cluster_arn]
  }
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.db_secret_arn]
  }
  statement {
    sid       = "RequestApprovalOnly"
    actions   = ["states:StartExecution"]
    resources = [var.approval_state_machine_arn]
  }
  statement {
    actions   = ["s3:PutObject"]
    resources = ["arn:aws:s3:::${var.artifacts_bucket}/workorders/*", "arn:aws:s3:::${var.artifacts_bucket}/traces/*"]
  }
  statement {
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [aws_ecr_repository.agent.arn]
  }
  statement {
    actions   = ["ecr:GetAuthorizationToken", "logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams", "logs:DescribeLogGroups", "xray:PutTraceSegments", "xray:PutTelemetryRecords", "cloudwatch:PutMetricData"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "runtime" {
  name   = "${var.name}-agent-runtime"
  role   = aws_iam_role.runtime.id
  policy = data.aws_iam_policy_document.runtime.json
}

resource "aws_bedrockagentcore_agent_runtime" "agent" {
  count              = var.image_tag == "" ? 0 : 1
  agent_runtime_name = "patchwork_ward_assistant"
  description        = "Ward Engineer's Assistant: Strands + Amazon Nova Pro, grounded tools over the defect register"
  role_arn           = aws_iam_role.runtime.arn
  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.agent.repository_url}:${var.image_tag}"
    }
  }
  network_configuration {
    network_mode = "PUBLIC"
  }
  protocol_configuration {
    server_protocol = "HTTP"
  }
  environment_variables = {
    PATCHWORK_DB_CLUSTER_ARN   = var.db_cluster_arn
    PATCHWORK_DB_SECRET_ARN    = var.db_secret_arn
    PATCHWORK_DB_NAME          = var.db_name
    PATCHWORK_APPROVAL_SFN     = var.approval_state_machine_arn
    PATCHWORK_ARTIFACTS_BUCKET = var.artifacts_bucket
  }
  depends_on = [aws_iam_role_policy.runtime]
}

output "repository_url" { value = aws_ecr_repository.agent.repository_url }
output "runtime_arn" { value = try(aws_bedrockagentcore_agent_runtime.agent[0].agent_runtime_arn, null) }
