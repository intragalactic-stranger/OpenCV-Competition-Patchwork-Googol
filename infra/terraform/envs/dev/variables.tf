variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "phase" {
  description = "Phase tag stamped on every resource (cost report groups by it)"
  type        = string
  default     = "4"
}

variable "batch_max_vcpus" {
  description = "Upper bound for the Spot compute environment: 10 perceive clips x 4 vCPU + assemble in one wave, plus a 32-vCPU evaluation job alongside (account Spot quota: 256 standard vCPU since 2026-10)"
  type        = number
  default     = 80
}

variable "db_name" {
  description = "Register database used by the pipeline, the approval workflow and the console. A fresh database per survey keeps older ones intact: `patchwork` holds the midpoint survey (seg-v3), `patchwork_final` the final one."
  type        = string
  default     = "patchwork_final"
}

variable "enable_console" {
  description = "Deploy the approval console (Cognito sign-in, HTTP API, Lambda). Off until the owner turns it on."
  type        = bool
  default     = false
}

variable "alert_emails" {
  description = "Who gets pipeline failure alarms (set in the git-ignored terraform.tfvars, like the budget alert)"
  type        = list(string)
}
