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

output "buckets" { value = module.storage.bucket_names }
output "ecr_repository_url" { value = module.batch.ecr_repository_url }
output "job_queue" { value = module.batch.job_queue }
output "job_definitions" { value = module.batch.job_definitions }
