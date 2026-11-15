terraform {
  required_version = ">= 1.10"
  required_providers {
    aws         = { source = "hashicorp/aws", version = "~> 5.0" }
    google      = { source = "hashicorp/google", version = "~> 6.0" }
    google-beta = { source = "hashicorp/google-beta", version = "~> 6.0" }
  }
  backend "s3" {
    key          = "arquifusion/gcp/terraform.tfstate"
    use_lockfile = true
  }
}

# AWS solo se lee (SSM /arquifusion/<stage>/api/url) para el endpoint de la suscripción push (gcp_billing = false)
provider "aws" {
  region = var.aws_region
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}

# Solo para google_project_service_identity (agente de servicio de Pub/Sub, notify.tf)
provider "google-beta" {
  project = var.gcp_project_id
  region  = var.gcp_region
}
