output "url" {
  description = "Where the agent answers."
  value       = "https://${cloudflare_dns_record.agent.name}/"
}
