output "collector_role_arn" {
  value = aws_iam_role.collector.arn
}

output "reader_policy_arn" {
  value = aws_iam_policy.reader.arn
}
