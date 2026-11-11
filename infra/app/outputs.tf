output "app_url" {
  description = "ブラウザで開くURL"
  value       = "http://${aws_lb.main.dns_name}"
}
