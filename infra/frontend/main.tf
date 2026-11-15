# Stack frontend (Persona C): hosting de la consola web (RF-15, RF-05, RF-11, RF-16).
# S3 privado + CloudFront con OAC: sin servidores ni costo fijo por hora (RNF serverless).
# El contenido NO lo sube Terraform: scripts/deploy_frontend.sh hace el build, `s3 sync` y la invalidación.

data "aws_caller_identity" "current" {}

# Learner Lab: no usar resource "aws_s3_bucket" (SCP bloquea GetBucketObjectLockConfiguration).
# Ver infra/modules/lab_s3_bucket. Ojo: terraform destroy ya no vacía ni borra este bucket.
module "web_bucket" {
  source = "../modules/lab_s3_bucket"
  name   = "${local.prefix}-web-${data.aws_caller_identity.current.account_id}"
  region = var.aws_region
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = module.web_bucket.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "${local.prefix}-web"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Política administrada "Managed-CachingOptimized". ID fijo y global de AWS: el Learner Lab deniega
# cloudfront:ListCachePolicies, así que no se puede resolver con un data source.
locals {
  caching_optimized_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"
}

resource "aws_cloudfront_distribution" "web" {
  enabled             = true
  comment             = "${local.prefix} consola web"
  default_root_object = "index.html"
  price_class         = "PriceClass_100"

  origin {
    origin_id                = "s3-web"
    domain_name              = module.web_bucket.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-web"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = local.caching_optimized_policy_id
    compress               = true
  }

  # SPA (react-router): rutas profundas devuelven index.html
  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }
  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

data "aws_iam_policy_document" "web" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${module.web_bucket.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.web.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket     = module.web_bucket.id
  policy     = data.aws_iam_policy_document.web.json
  depends_on = [aws_s3_bucket_public_access_block.web]
}

resource "aws_ssm_parameter" "web_url" {
  name  = "/arquifusion/${var.stage}/frontend/url"
  type  = "String"
  value = "https://${aws_cloudfront_distribution.web.domain_name}"
}
