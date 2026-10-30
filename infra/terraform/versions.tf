terraform {
  required_version = ">= 1.9.0, < 2.0.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
  # Configure an encrypted remote backend before team use. Never commit state.
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "pipefoundry", Environment = var.environment, ManagedBy = "terraform" }
  }
}
