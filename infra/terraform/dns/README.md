# DNS (step 6.4)

The cloud server's public name, `agent.efi-agent.dev`, as an A record on the server's
Elastic IP (read from the cloud stack's state), and a CAA record so that only Let's Encrypt
may issue certificates for the domain. Not proxied through Cloudflare: Traefik on the server
ends TLS itself.

```bash
# The token: Cloudflare API token, Zone DNS Edit on efi-agent.dev only, kept in the
# git-ignored deploy/compose/.env as CLOUDFLARE_API_TOKEN. Into the environment, never a file:
set -a; . deploy/compose/.env; set +a
export TF_VAR_cloudflare_api_token="$CLOUDFLARE_API_TOKEN" AWS_PROFILE=sa-admin
terraform -chdir=infra/terraform/dns init
terraform -chdir=infra/terraform/dns apply
```

Costs nothing: Cloudflare's DNS is free; the domain itself is paid yearly at the registrar.
CI checks this stack on every pull request; it plans it only when the repository has a
`CLOUDFLARE_READ_TOKEN` secret (a read-only token for the zone).
