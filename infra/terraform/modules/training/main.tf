# SageMaker training (second half: GPU). Only the execution role lives here; jobs are launched from
# scripts/aws/submit_sagemaker.py with a hard MaxRuntime, so nothing runs (or costs) between jobs.

variable "name" { type = string }
variable "boundary_arn" { type = string }
variable "datasets_bucket" { type = string }
variable "artifacts_bucket" { type = string }

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sagemaker" {
  name                 = "${var.name}-sagemaker-train"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  permissions_boundary = var.boundary_arn
}

data "aws_iam_policy_document" "sagemaker" {
  statement {
    sid       = "ReadDatasets"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.datasets_bucket}", "arn:aws:s3:::${var.datasets_bucket}/*"]
  }
  statement {
    sid       = "ModelsAndCheckpoints"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.artifacts_bucket}", "arn:aws:s3:::${var.artifacts_bucket}/*"]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams", "cloudwatch:PutMetricData"]
    resources = ["*"]
  }
  statement {
    sid       = "PullAwsDeepLearningContainers"
    actions   = ["ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "sagemaker" {
  name   = "${var.name}-sagemaker-train"
  role   = aws_iam_role.sagemaker.id
  policy = data.aws_iam_policy_document.sagemaker.json
}

output "role_arn" { value = aws_iam_role.sagemaker.arn }
