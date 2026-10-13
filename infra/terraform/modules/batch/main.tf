# AWS Batch on Graviton Spot: ECR repo, compute environment (min 0 vCPU), queue, job definitions.
# Every IAM role carries the patchwork-boundary permissions boundary (see infra/iam/README).

variable "name" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_id" { type = string }
variable "boundary_arn" { type = string }
variable "bucket_arns" { type = map(string) }
variable "max_vcpus" {
  type    = number
  default = 32
}
variable "instance_types" {
  type    = list(string)
  default = ["c7g", "c6g", "m7g", "c8g"]
}
variable "image_tag" {
  type    = string
  default = "latest"
}
variable "instance_tags" {
  type    = map(string)
  default = {}
}

data "aws_region" "current" {}

# ---------- container registry ----------
resource "aws_ecr_repository" "batch" {
  name                 = "${var.name}-batch"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "train" {
  name                 = "${var.name}-train"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "batch" {
  for_each   = { batch = aws_ecr_repository.batch.name, train = aws_ecr_repository.train.name }
  repository = each.value
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the last 10 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}

# ---------- IAM ----------
data "aws_iam_policy_document" "ec2_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name                 = "${var.name}-batch-instance"
  assume_role_policy   = data.aws_iam_policy_document.ec2_trust.json
  permissions_boundary = var.boundary_arn
}

resource "aws_iam_role_policy_attachment" "instance_ecs" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_instance_profile" "instance" {
  name = "${var.name}-batch-instance"
  role = aws_iam_role.instance.name
}

resource "aws_iam_role" "job" {
  name                 = "${var.name}-batch-job"
  assume_role_policy   = data.aws_iam_policy_document.ecs_tasks_trust.json
  permissions_boundary = var.boundary_arn
}

data "aws_iam_policy_document" "job" {
  statement {
    sid       = "ListBuckets"
    actions   = ["s3:ListBucket"]
    resources = values(var.bucket_arns)
  }
  statement {
    sid       = "ReadWriteObjects"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
    resources = [for a in values(var.bucket_arns) : "${a}/*"]
  }
}

resource "aws_iam_role_policy" "job" {
  name   = "s3-data"
  role   = aws_iam_role.job.id
  policy = data.aws_iam_policy_document.job.json
}

# ---------- compute ----------
resource "aws_batch_compute_environment" "spot" {
  name = "${var.name}-graviton-spot"
  type = "MANAGED"

  compute_resources {
    type                = "SPOT"
    allocation_strategy = "SPOT_PRICE_CAPACITY_OPTIMIZED"
    min_vcpus           = 0
    desired_vcpus       = 0
    max_vcpus           = var.max_vcpus
    instance_type       = var.instance_types
    instance_role       = aws_iam_instance_profile.instance.arn
    subnets             = var.subnet_ids
    security_group_ids  = [var.security_group_id]
    tags                = merge(var.instance_tags, { Name = "${var.name}-batch-worker" })
    ec2_configuration {
      image_type = "ECS_AL2023"
    }
  }

  lifecycle {
    ignore_changes = [compute_resources[0].desired_vcpus]
  }
}

resource "aws_batch_job_queue" "spot" {
  name     = "${var.name}-spot"
  state    = "ENABLED"
  priority = 1
  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.spot.arn
  }
}

resource "aws_cloudwatch_log_group" "batch" {
  name              = "/${var.name}/batch"
  retention_in_days = 14
}

locals {
  image = "${aws_ecr_repository.batch.repository_url}:${var.image_tag}"
  retry = {
    attempts = 3
    evaluateOnExit = [
      { onStatusReason = "Host EC2*", action = "RETRY" },
      { onReason = "CannotPullContainerError*", action = "RETRY" },
      { onReason = "*", action = "EXIT" },
    ]
  }
}

resource "aws_batch_job_definition" "synth_render" {
  name                  = "${var.name}-synth-render"
  type                  = "container"
  platform_capabilities = ["EC2"]
  propagate_tags        = true
  retry_strategy {
    attempts = local.retry.attempts
    dynamic "evaluate_on_exit" {
      for_each = local.retry.evaluateOnExit
      content {
        action           = evaluate_on_exit.value.action
        on_status_reason = try(evaluate_on_exit.value.onStatusReason, null)
        on_reason        = try(evaluate_on_exit.value.onReason, null)
      }
    }
  }
  timeout {
    attempt_duration_seconds = 7200
  }
  container_properties = jsonencode({
    image      = local.image
    command    = ["patchwork.pipeline.synth_job", "--help"]
    jobRoleArn = aws_iam_role.job.arn
    resourceRequirements = [
      { type = "VCPU", value = "2" },
      { type = "MEMORY", value = "3584" },
    ]
    environment = [{ name = "OMP_NUM_THREADS", value = "2" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.batch.name
        "awslogs-region"        = data.aws_region.current.region
        "awslogs-stream-prefix" = "synth"
      }
    }
  })
}

# CPU training (decision D-25) and dataset preparation, both from the training image
locals {
  train_image = "${aws_ecr_repository.train.repository_url}:${var.image_tag}"
  train_jobs = {
    prepare   = { vcpu = 4, memory = 15000, timeout = 7200, command = ["training.prepare", "--help"] }
    train-cpu = { vcpu = 32, memory = 60000, timeout = 36000, command = ["training.train", "--help"] }
  }
}

resource "aws_batch_job_definition" "train" {
  for_each              = local.train_jobs
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
    image      = local.train_image
    command    = each.value.command
    jobRoleArn = aws_iam_role.job.arn
    resourceRequirements = [
      { type = "VCPU", value = tostring(each.value.vcpu) },
      { type = "MEMORY", value = tostring(each.value.memory) },
    ]
    linuxParameters = { sharedMemorySize = 8192 }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.batch.name
        "awslogs-region"        = data.aws_region.current.region
        "awslogs-stream-prefix" = each.key
      }
    }
  })
}

output "ecr_repository_url" { value = aws_ecr_repository.batch.repository_url }
output "ecr_train_repository_url" { value = aws_ecr_repository.train.repository_url }
output "job_queue" { value = aws_batch_job_queue.spot.name }
output "job_definitions" {
  value = merge(
    { synth_render = aws_batch_job_definition.synth_render.name },
    { for k, v in aws_batch_job_definition.train : k => v.name },
  )
}
output "job_role_arn" { value = aws_iam_role.job.arn }
