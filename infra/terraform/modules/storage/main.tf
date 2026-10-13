# S3 buckets. raw: uploaded clips (30-day expiry). artifacts: crops, overlays, traces, models.
# datasets: open + synthetic data. SSE-S3 everywhere, public access blocked.

variable "prefix" { type = string }
variable "raw_expiry_days" {
  type    = number
  default = 30
}

locals {
  buckets = {
    raw       = "${var.prefix}-raw"
    artifacts = "${var.prefix}-artifacts"
    datasets  = "${var.prefix}-datasets"
  }
}

resource "aws_s3_bucket" "b" {
  for_each = local.buckets
  bucket   = each.value
}

resource "aws_s3_bucket_public_access_block" "b" {
  for_each                = aws_s3_bucket.b
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "b" {
  for_each = aws_s3_bucket.b
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "b" {
  for_each = aws_s3_bucket.b
  bucket   = each.value.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "raw" {
  bucket = aws_s3_bucket.b["raw"].id
  rule {
    id     = "expire-raw-clips"
    status = "Enabled"
    filter {}
    expiration {
      days = var.raw_expiry_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 2
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "other" {
  for_each = { for k, v in aws_s3_bucket.b : k => v if k != "raw" }
  bucket   = each.value.id
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 2
    }
  }
}

# EventBridge notifications on the raw bucket (the ingest rule is added in the pipeline module)
resource "aws_s3_bucket_notification" "raw" {
  bucket      = aws_s3_bucket.b["raw"].id
  eventbridge = true
}

output "bucket_names" { value = { for k, v in aws_s3_bucket.b : k => v.bucket } }
output "bucket_arns" { value = { for k, v in aws_s3_bucket.b : k => v.arn } }
