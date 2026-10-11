output "application_url" {
  description = "TaskFlow HTTPS endpoint."
  value       = "https://${var.app_domain}"
}

output "load_balancer_dns_name" {
  description = "Configure this name as an A/ALIAS or CNAME for app_domain when using external DNS."
  value       = aws_lb.taskflow.dns_name
}

output "ecr_repository_url" {
  description = "ECR repository to use for TaskFlow container images."
  value       = aws_ecr_repository.taskflow.repository_url
}

output "github_deploy_role_arn" {
  description = "Set this as the AWS_DEPLOY_ROLE_ARN GitHub Actions repository variable."
  value       = aws_iam_role.github_deploy.arn
}

output "ecs_cluster_name" {
  description = "Set this as the ECS_CLUSTER_NAME GitHub Actions repository variable."
  value       = aws_ecs_cluster.taskflow.name
}

output "ecs_service_name" {
  description = "Set this as the ECS_SERVICE_NAME GitHub Actions repository variable."
  value       = aws_ecs_service.taskflow.name
}

output "ecs_task_definition_family" {
  description = "Set this as the ECS_TASK_DEFINITION_FAMILY GitHub Actions repository variable."
  value       = aws_ecs_task_definition.taskflow.family
}

output "aws_region" {
  description = "Set this as the AWS_REGION GitHub Actions repository variable."
  value       = var.aws_region
}

output "application_secret_arn" {
  description = "Add a secret value to this Secrets Manager secret before starting the service."
  value       = aws_secretsmanager_secret.application_key.arn
}

output "application_database_secret_arn" {
  description = "Add the least-privilege username/password JSON before starting the service."
  value       = aws_secretsmanager_secret.application_database.arn
}

output "database_master_secret_arn" {
  description = "RDS-generated administrator credentials; use only for initial database-user provisioning."
  value       = aws_db_instance.taskflow.master_user_secret[0].secret_arn
}

output "database_endpoint" {
  description = "Private PostgreSQL endpoint used by the ECS tasks."
  value       = aws_db_instance.taskflow.address
}

output "upload_storage_id" {
  description = "Encrypted EFS file system used for shared TaskFlow uploads."
  value       = aws_efs_file_system.taskflow.id
}

output "backup_vault_name" {
  description = "AWS Backup vault containing encrypted daily RDS backups."
  value       = aws_backup_vault.taskflow.name
}

output "alerts_topic_arn" {
  description = "SNS topic receiving CloudWatch alarm notifications."
  value       = aws_sns_topic.alerts.arn
}
