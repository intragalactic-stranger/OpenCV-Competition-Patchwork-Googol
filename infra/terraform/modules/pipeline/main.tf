# Cloud pipeline: S3 (raw upload, manifest.json last) -> EventBridge -> Step Functions
#   -> Batch "perceive" array job (one child per clip, Graviton Spot) -> Batch "assemble" job
#   -> register (Aurora, Data API) + map viewer (S3 + CloudFront).
# All services first-party (decision D-27). Every role carries the patchwork-boundary.

variable "name" { type = string }
variable "boundary_arn" { type = string }
variable "raw_bucket" { type = string }
variable "artifacts_bucket" { type = string }
variable "job_queue_arn" { type = string }
variable "job_role_name" { type = string }
variable "job_role_arn" { type = string }
variable "image" { type = string }
variable "log_group" { type = string }
variable "db_cluster_arn" { type = string }
variable "db_secret_arn" { type = string }
variable "site_bucket" { type = string }
variable "cf_distribution_id" { type = string }
variable "maps_key_name" {
  type    = string
  default = "patchwork-viewer-maps"
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  env = [
    { name = "PATCHWORK_DB_CLUSTER_ARN", value = var.db_cluster_arn },
    { name = "PATCHWORK_DB_SECRET_ARN", value = var.db_secret_arn },
    { name = "PATCHWORK_SITE_BUCKET", value = var.site_bucket },
    { name = "PATCHWORK_CF_DISTRIBUTION", value = var.cf_distribution_id },
    { name = "PATCHWORK_MAPS_KEY_NAME", value = var.maps_key_name },
    { name = "OMP_NUM_THREADS", value = "4" },
  ]
  jobs = {
    perceive = { vcpu = 4, memory = 7000, timeout = 5400 }
    assemble = { vcpu = 4, memory = 7000, timeout = 5400 }
  }
}

# ---------- extra permissions for the Batch job role (register, viewer) ----------
data "aws_iam_policy_document" "job_extra" {
  statement {
    sid       = "RegisterDataApi"
    actions   = ["rds-data:ExecuteStatement", "rds-data:BatchExecuteStatement"]
    resources = [var.db_cluster_arn]
  }
  statement {
    sid       = "RegisterSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.db_secret_arn]
  }
  statement {
    sid       = "ViewerSite"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.site_bucket}", "arn:aws:s3:::${var.site_bucket}/*"]
  }
  statement {
    sid       = "ViewerInvalidate"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = ["arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/${var.cf_distribution_id}"]
  }
  statement {
    sid       = "MapsKey"
    actions   = ["geo:DescribeKey"]
    resources = ["arn:aws:geo:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:api-key/${var.maps_key_name}"]
  }
}

resource "aws_iam_role_policy" "job_extra" {
  name   = "register-and-viewer"
  role   = var.job_role_name
  policy = data.aws_iam_policy_document.job_extra.json
}

# ---------- job definitions ----------
resource "aws_batch_job_definition" "stage" {
  for_each              = local.jobs
  name                  = "${var.name}-${each.key}"
  type                  = "container"
  platform_capabilities = ["EC2"]
  propagate_tags        = true
  retry_strategy {
    attempts = 3
    evaluate_on_exit {
      action           = "RETRY"
      on_status_reason = "Host EC2*"
    }
    evaluate_on_exit {
      action    = "EXIT"
      on_reason = "*"
    }
  }
  timeout {
    attempt_duration_seconds = each.value.timeout
  }
  container_properties = jsonencode({
    image       = var.image
    command     = ["patchwork.pipeline.batch", each.key, "--help"]
    jobRoleArn  = var.job_role_arn
    environment = local.env
    resourceRequirements = [
      { type = "VCPU", value = tostring(each.value.vcpu) },
      { type = "MEMORY", value = tostring(each.value.memory) },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = var.log_group
        "awslogs-region"        = data.aws_region.current.region
        "awslogs-stream-prefix" = each.key
      }
    }
  })
}

# ---------- Step Functions ----------
data "aws_iam_policy_document" "sfn_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name                 = "${var.name}-pipeline-sfn"
  assume_role_policy   = data.aws_iam_policy_document.sfn_trust.json
  permissions_boundary = var.boundary_arn
}

data "aws_iam_policy_document" "sfn" {
  statement {
    actions   = ["batch:SubmitJob", "batch:DescribeJobs", "batch:TerminateJob", "batch:TagResource"]
    resources = ["*"]
  }
  statement {
    sid       = "SyncIntegrationRule"
    actions   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
    resources = ["arn:aws:events:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:rule/StepFunctionsGetEventsForBatchJobsRule"]
  }
  statement {
    actions   = ["s3:GetObject"]
    resources = ["arn:aws:s3:::${var.raw_bucket}/*"]
  }
  statement {
    sid = "ExecutionLogs"
    actions = [
      "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "sfn" {
  name   = "pipeline"
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn.json
}

resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/${var.name}/pipeline-sfn"
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${var.name}-process-pass"
  role_arn = aws_iam_role.sfn.arn
  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }
  definition = jsonencode({
    Comment = "Process one uploaded survey pass: perceive every clip in parallel, then assemble, register, publish"
    StartAt = "ReadManifest"
    States = {
      ReadManifest = {
        Type       = "Task"
        Resource   = "arn:aws:states:::aws-sdk:s3:getObject"
        Parameters = { "Bucket.$" = "$.bucket", "Key.$" = "$.key" }
        ResultSelector = {
          "manifest.$" = "States.StringToJson($.Body)"
        }
        ResultPath = "$.m"
        Next       = "Perceive"
      }
      Perceive = {
        Type     = "Task"
        Resource = "arn:aws:states:::batch:submitJob.sync"
        Parameters = {
          "JobName.$"     = "States.Format('perceive-{}-{}', $.m.manifest.run_id, $.m.manifest.pass)"
          JobQueue        = var.job_queue_arn
          JobDefinition   = aws_batch_job_definition.stage["perceive"].arn
          ArrayProperties = { "Size.$" = "$.m.manifest.n_clips" }
          ContainerOverrides = {
            "Command.$" = "States.Array('patchwork.pipeline.batch', 'perceive', '--pass-uri', States.Format('s3://${var.raw_bucket}/{}/{}', $.m.manifest.run_id, $.m.manifest.pass), '--run-uri', States.Format('s3://${var.artifacts_bucket}/runs/{}', $.m.manifest.run_id), '--model-uri', States.Format('s3://${var.artifacts_bucket}/models/{}/model.onnx', $.m.manifest.model))"
          }
          Tags = { Project = "patchwork", Phase = "4" }
        }
        ResultPath = null
        Retry      = [{ ErrorEquals = ["States.TaskFailed"], MaxAttempts = 1, IntervalSeconds = 30 }]
        Next       = "Assemble"
      }
      Assemble = {
        Type     = "Task"
        Resource = "arn:aws:states:::batch:submitJob.sync"
        Parameters = {
          "JobName.$"   = "States.Format('assemble-{}-{}', $.m.manifest.run_id, $.m.manifest.pass)"
          JobQueue      = var.job_queue_arn
          JobDefinition = aws_batch_job_definition.stage["assemble"].arn
          ContainerOverrides = {
            "Command.$" = "States.Array('patchwork.pipeline.batch', 'assemble', '--pass-uri', States.Format('s3://${var.raw_bucket}/{}/{}', $.m.manifest.run_id, $.m.manifest.pass), '--run-uri', States.Format('s3://${var.artifacts_bucket}/runs/{}', $.m.manifest.run_id), '--model-uri', States.Format('s3://${var.artifacts_bucket}/models/{}/model.onnx', $.m.manifest.model), '--model-version', $.m.manifest.model, '--load-register', '--publish', '--source', $.m.manifest.source)"
          }
          Tags = { Project = "patchwork", Phase = "4" }
        }
        ResultPath = null
        End        = true
      }
    }
  })
}

# ---------- trigger: manifest.json written last by the uploader ----------
resource "aws_cloudwatch_event_rule" "manifest" {
  name        = "${var.name}-pass-uploaded"
  description = "A survey pass finished uploading (manifest.json written last)"
  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = { name = [var.raw_bucket] }
      object = { key = [{ suffix = "manifest.json" }] }
    }
  })
}

data "aws_iam_policy_document" "events_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "events" {
  name                 = "${var.name}-pipeline-events"
  assume_role_policy   = data.aws_iam_policy_document.events_trust.json
  permissions_boundary = var.boundary_arn
}

resource "aws_iam_role_policy" "events" {
  name = "start-pipeline"
  role = aws_iam_role.events.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "states:StartExecution", Resource = aws_sfn_state_machine.pipeline.arn }]
  })
}

resource "aws_cloudwatch_event_target" "sfn" {
  rule     = aws_cloudwatch_event_rule.manifest.name
  arn      = aws_sfn_state_machine.pipeline.arn
  role_arn = aws_iam_role.events.arn
  input_transformer {
    input_paths    = { bucket = "$.detail.bucket.name", key = "$.detail.object.key" }
    input_template = "{\"bucket\": <bucket>, \"key\": <key>}"
  }
}

output "state_machine_arn" { value = aws_sfn_state_machine.pipeline.arn }
