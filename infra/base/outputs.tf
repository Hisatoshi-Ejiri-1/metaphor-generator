output "table_name" {
  value = aws_dynamodb_table.timeline.name
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.app.name
}
