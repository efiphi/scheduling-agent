variable "region" {
  description = "Where the Terraform state lives."
  type        = string
  default     = "eu-central-1"
}

variable "cloudflare_api_token" {
  description = <<-EOT
    Cloudflare API token, DNS edit on the zone only. From the environment, never a file in
    the repository: TF_VAR_cloudflare_api_token (README).
  EOT
  type        = string
  sensitive   = true
}

variable "zone" {
  description = "The domain, registered at Cloudflare."
  type        = string
  default     = "efi-agent.dev"
}

variable "host" {
  description = "The name the agent answers on, inside the zone."
  type        = string
  default     = "agent"
}
