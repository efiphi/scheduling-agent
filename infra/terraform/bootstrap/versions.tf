terraform {
  required_version = "~> 1.17.0"

  required_providers {
    # Pinned to an exact release at least two weeks old (T20); the lock file pins its hashes.
    aws = {
      source  = "hashicorp/aws"
      version = "6.71.0"
    }
  }

  # This stack creates the state bucket itself, so its first apply runs with local state; then
  # `terraform init -migrate-state` moves it here (README.md).
  backend "s3" {
    bucket       = "sa-tfstate-571771087482"
    key          = "bootstrap/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true # S3-native locking: two applies cannot run at once
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project    = "scheduling-agent"
      managed-by = "terraform"
      stack      = "bootstrap"
    }
  }
}
