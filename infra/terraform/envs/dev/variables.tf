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
