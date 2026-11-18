variable "region" {
  description = "Where everything lives (ADR-023)."
  type        = string
  default     = "eu-central-1"
}

variable "github_repository" {
  description = "The only repository whose CI may assume the plan role."
  type        = string
  default     = "efiphi/scheduling-agent"
}

variable "monthly_budget_usd" {
  description = "The whole account's monthly budget; email alerts at 85%, 100% and forecast 100%."
  type        = number
  default     = 20
}

variable "alert_email" {
  description = "Where budget alerts go. Not committed: set in terraform.tfvars, which git ignores."
  type        = string
  sensitive   = true
}
