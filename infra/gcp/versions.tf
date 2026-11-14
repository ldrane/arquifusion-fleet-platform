terraform {
  required_version = ">= 1.10"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.0" }
    google = { source = "hashicorp/google", version = "~> 6.0" }
  }
  backend "s3" {
    key          = "arquifusion/gcp/terraform.tfstate"
    use_lockfile = true
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}
