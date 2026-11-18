terraform {
  required_version = "~> 1.17.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.71.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "5.28.1"
    }
  }

  backend "s3" {
    bucket       = "sa-tfstate-571771087482"
    key          = "dns/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true
  }
}

# Only to read the cloud stack's state (the server's address).
provider "aws" {
  region = var.region
}

# A token scoped to this one zone, DNS edit only (deploy/compose/.env, never committed).
provider "cloudflare" {
  api_token = var.cloudflare_api_token
}
