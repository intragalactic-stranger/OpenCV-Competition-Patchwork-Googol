variable "region" {
  description = "AWS region for all Patchwork resources"
  type        = string
  default     = "ap-south-1"
}

variable "monthly_budget_usd" {
  description = "Planned monthly usage paid from promotional credits (reported by make cost-report)"
  type        = number
  default     = 300
}

variable "real_spend_alert_usd" {
  description = "Monthly budget on cost AFTER credits; alerts on the first cent of real spend"
  type        = number
  default     = 1
}

variable "alert_emails" {
  description = "Email addresses that receive budget alerts (set in terraform.tfvars, which is git-ignored)"
  type        = list(string)
}
