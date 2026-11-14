output "bucket" {
  value = module.web_bucket.id
}

output "distribution_id" {
  value = aws_cloudfront_distribution.web.id
}

output "url" {
  description = "Usar como cors_origin en infra/base e infra/query si se restringe el origen"
  value       = "https://${aws_cloudfront_distribution.web.domain_name}"
}
