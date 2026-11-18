# The public name of the cloud server (step 6.4, ADR-023), kept as code like the server.
#
# The address comes from the cloud stack's own state, so a new Elastic IP updates the
# record on the next apply, with nothing copied by hand.

data "terraform_remote_state" "cloud" {
  backend = "s3"
  config = {
    bucket = "sa-tfstate-571771087482"
    key    = "cloud/terraform.tfstate"
    region = var.region
  }
}

data "cloudflare_zone" "main" {
  filter = {
    name = var.zone
  }
}

# DNS only, not through Cloudflare's proxy: Traefik on the server holds the certificate and
# ends TLS itself, so no third party sees the traffic in the clear.
resource "cloudflare_dns_record" "agent" {
  zone_id = data.cloudflare_zone.main.zone_id
  name    = "${var.host}.${var.zone}"
  type    = "A"
  content = data.terraform_remote_state.cloud.outputs.public_ip
  ttl     = 300
  proxied = false
  comment = "scheduling-agent cloud server (infra/terraform/dns)"
}

# Only Let's Encrypt may issue certificates for this domain: a certificate authority asked
# by anyone else for a certificate here must refuse (CAA, RFC 8659).
resource "cloudflare_dns_record" "caa" {
  zone_id = data.cloudflare_zone.main.zone_id
  name    = var.zone
  type    = "CAA"
  ttl     = 3600
  data = {
    flags = 0
    tag   = "issue"
    value = "letsencrypt.org"
  }
  comment = "Only Let's Encrypt issues certificates (infra/terraform/dns)"
}
