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
  description = "Upper bound for the Spot compute environment (account Spot quota is 32 standard vCPU)"
  type        = number
  default     = 32
}

variable "db_name" {
  description = "Register database the console and the agent read (a fresh database per survey keeps old ones intact)"
  type        = string
  default     = "patchwork"
}

variable "enable_console" {
  description = "Deploy the approval console (Cognito sign-in, HTTP API, Lambda). Off until the owner turns it on."
  type        = bool
  default     = false
}
