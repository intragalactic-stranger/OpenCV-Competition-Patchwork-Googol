variable "region" {
  description = "AWS region for all Patchwork resources"
  type        = string
  default     = "ap-south-1"
}

variable "monthly_budget_usd" {
  description = "Monthly spend cap that triggers the budget alerts"
  type        = number
  default     = 300
}

variable "alert_emails" {
  description = "Email addresses that receive budget alerts (set in terraform.tfvars, which is git-ignored)"
  type        = list(string)
}
