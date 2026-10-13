# Bootstrap: run once with local state.
# Creates the remote-state bucket (S3 native locking, no DynamoDB table needed with Terraform >= 1.10)
# and the monthly AWS Budget with alerts.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project = "patchwork"
      Phase   = "0"
      Owner   = "googol"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id   = data.aws_caller_identity.current.account_id
  state_bucket = "patchwork-${local.account_id}-tfstate"
}

resource "aws_s3_bucket" "tfstate" {
  bucket = local.state_bucket
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

# Real-money guardrail. The account runs on AWS promotional credits and nothing may cost real money.
# With include_credit = true the budget measures cost *after* credits, so it stays at $0 while credits
# cover everything; the first uncovered cent (e.g. a Marketplace product) emails the owner.
# Account-wide on purpose (no tag filter): any real charge matters, not only Patchwork's.
# Credit *consumption* (gross usage vs the $300/month plan) is tracked by `make cost-report`.
resource "aws_budgets_budget" "real_spend" {
  name         = "patchwork-real-spend"
  budget_type  = "COST"
  limit_amount = tostring(var.real_spend_alert_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_types {
    include_credit = true
    include_refund = true
  }

  # > 1 % of $1 = the first cent of real (uncovered) spend
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 1
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.alert_emails
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = var.alert_emails
  }
}

output "state_bucket" {
  value = aws_s3_bucket.tfstate.bucket
}

output "account_id" {
  value = local.account_id
}
