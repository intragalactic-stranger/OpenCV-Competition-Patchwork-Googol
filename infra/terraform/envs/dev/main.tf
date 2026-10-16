# Patchwork dev environment (ap-south-1). State lives in the bootstrap bucket with S3-native locking.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
  backend "s3" {
    bucket       = "patchwork-682839842398-tfstate"
    key          = "envs/dev/terraform.tfstate"
    region       = "ap-south-1"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project = "patchwork"
      Phase   = var.phase
      Owner   = "googol"
      Env     = "dev"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name         = "patchwork"
  prefix       = "patchwork-${data.aws_caller_identity.current.account_id}"
  boundary_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/patchwork-boundary"
}

module "network" {
  source = "../../modules/network"
  name   = local.name
  cidr   = "10.42.0.0/16"
}

module "storage" {
  source = "../../modules/storage"
  prefix = local.prefix
}

module "batch" {
  source            = "../../modules/batch"
  name              = local.name
  subnet_ids        = module.network.public_subnet_ids
  security_group_id = module.network.batch_security_group_id
  boundary_arn      = local.boundary_arn
  bucket_arns       = module.storage.bucket_arns
  max_vcpus         = var.batch_max_vcpus
  # EC2 instances launched by Batch do not inherit provider default_tags: tag them for cost allocation
  instance_tags = { Project = "patchwork", Phase = var.phase, Owner = "googol", Env = "dev" }
}

module "db" {
  source     = "../../modules/db"
  name       = local.name
  vpc_id     = module.network.vpc_id
  subnet_ids = module.network.private_subnet_ids
}

module "viewer" {
  source = "../../modules/viewer"
  prefix = local.prefix
}

module "pipeline" {
  source             = "../../modules/pipeline"
  name               = local.name
  boundary_arn       = local.boundary_arn
  raw_bucket         = module.storage.bucket_names["raw"]
  artifacts_bucket   = module.storage.bucket_names["artifacts"]
  job_queue_arn      = module.batch.job_queue_arn
  job_role_name      = module.batch.job_role_name
  job_role_arn       = module.batch.job_role_arn
  image              = module.batch.image
  log_group          = module.batch.log_group
  db_cluster_arn     = module.db.cluster_arn
  db_secret_arn      = module.db.secret_arn
  site_bucket        = module.viewer.bucket
  cf_distribution_id = module.viewer.distribution_id
}

module "training" {
  source           = "../../modules/training"
  name             = local.name
  boundary_arn     = local.boundary_arn
  datasets_bucket  = module.storage.bucket_names["datasets"]
  artifacts_bucket = module.storage.bucket_names["artifacts"]
}

module "console" {
  count                      = var.enable_console ? 1 : 0
  source                     = "../../modules/console"
  name                       = local.name
  prefix                     = local.prefix
  boundary_arn               = local.boundary_arn
  site_url                   = module.viewer.url
  db_cluster_arn             = module.db.cluster_arn
  db_secret_arn              = module.db.secret_arn
  db_name                    = var.db_name
  approval_state_machine_arn = module.pipeline.approval_state_machine_arn
  artifacts_bucket           = module.storage.bucket_names["artifacts"]
  source_file                = "${path.root}/../../../../src/patchwork/api/console.py"
}

output "buckets" { value = module.storage.bucket_names }
output "ecr_repository_url" { value = module.batch.ecr_repository_url }
output "job_queue" { value = module.batch.job_queue }
output "job_definitions" { value = module.batch.job_definitions }
output "db_cluster_arn" { value = module.db.cluster_arn }
output "db_secret_arn" { value = module.db.secret_arn }
output "viewer_url" { value = module.viewer.url }
output "viewer_bucket" { value = module.viewer.bucket }
output "viewer_distribution_id" { value = module.viewer.distribution_id }
output "pipeline_state_machine" { value = module.pipeline.state_machine_arn }
output "approval_state_machine" { value = module.pipeline.approval_state_machine_arn }
output "sagemaker_role_arn" { value = module.training.role_arn }
output "console" {
  value = var.enable_console ? {
    api_url      = module.console[0].api_url
    user_pool_id = module.console[0].user_pool_id
    client_id    = module.console[0].client_id
    auth_domain  = module.console[0].auth_domain
  } : null
}
