terraform {
  required_version = "~> 1.17.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.71.0"
    }
  }

  backend "s3" {
    bucket       = "sa-tfstate-571771087482"
    key          = "cloud/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project    = "scheduling-agent"
      managed-by = "terraform"
      stack      = "cloud"
    }
  }
}
