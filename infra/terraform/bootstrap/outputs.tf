output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

output "github_plan_role_arn" {
  description = "For the Terraform workflow's aws-actions/configure-aws-credentials step."
  value       = aws_iam_role.github_plan.arn
}
