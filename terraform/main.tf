terraform {
  required_version = ">= 1.5.0"

  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Application = var.app_name
      ManagedBy   = "Terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name               = var.app_name
  availability_zones = slice(data.aws_availability_zones.available.names, 0, 2)
  public_cidrs       = [for index in range(2) : cidrsubnet(var.vpc_cidr, 8, index)]
  private_cidrs      = [for index in range(2) : cidrsubnet(var.vpc_cidr, 8, index + 2)]
  github_subject     = "repo:${var.github_repository}:ref:refs/heads/${var.github_branch}"
}

resource "aws_kms_key" "taskflow" {
  description             = "Encryption key for TaskFlow database, secrets, and backups"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "taskflow" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.taskflow.key_id
}

resource "aws_vpc" "taskflow" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = "${local.name}-vpc" }
}

resource "aws_internet_gateway" "taskflow" {
  vpc_id = aws_vpc.taskflow.id
  tags   = { Name = "${local.name}-igw" }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.taskflow.id
  cidr_block              = local.public_cidrs[count.index]
  availability_zone       = local.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = { Name = "${local.name}-public-${count.index + 1}" }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.taskflow.id
  cidr_block        = local.private_cidrs[count.index]
  availability_zone = local.availability_zones[count.index]

  tags = { Name = "${local.name}-private-${count.index + 1}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.taskflow.id
  tags   = { Name = "${local.name}-public" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.taskflow.id
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  count  = 2
  vpc_id = aws_vpc.taskflow.id
  tags   = { Name = "${local.name}-private-${count.index + 1}" }
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

resource "aws_security_group" "load_balancer" {
  name        = "${local.name}-alb"
  description = "Public HTTPS entry point for TaskFlow"
  vpc_id      = aws_vpc.taskflow.id

  ingress {
    description = "HTTP redirect to HTTPS"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS application traffic"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

}

resource "aws_security_group" "application" {
  name        = "${local.name}-app"
  description = "TaskFlow tasks accept traffic only from the load balancer"
  vpc_id      = aws_vpc.taskflow.id

  ingress {
    from_port       = 5000
    to_port         = 5000
    protocol        = "tcp"
    security_groups = [aws_security_group.load_balancer.id]
  }

  egress {
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }
}

resource "aws_security_group" "database" {
  name        = "${local.name}-database"
  description = "PostgreSQL is reachable only from TaskFlow application tasks"
  vpc_id      = aws_vpc.taskflow.id
  egress      = []

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.application.id]
  }
}

resource "aws_security_group" "file_storage" {
  name        = "${local.name}-file-storage"
  description = "Encrypted shared file storage for TaskFlow uploads"
  vpc_id      = aws_vpc.taskflow.id
  egress      = []

  ingress {
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.application.id]
  }
}

resource "aws_efs_file_system" "taskflow" {
  creation_token   = "${local.name}-uploads"
  encrypted        = true
  kms_key_id       = aws_kms_key.taskflow.arn
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  tags = {
    Name   = "${local.name}-uploads"
    Backup = "true"
  }
}

resource "aws_efs_mount_target" "taskflow" {
  count           = 2
  file_system_id  = aws_efs_file_system.taskflow.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.file_storage.id]
}

resource "aws_efs_access_point" "taskflow_uploads" {
  file_system_id = aws_efs_file_system.taskflow.id

  posix_user {
    gid = 10001
    uid = 10001
  }

  root_directory {
    path = "/taskflow/uploads"
    creation_info {
      owner_gid   = 10001
      owner_uid   = 10001
      permissions = "0750"
    }
  }
}

resource "aws_ecr_repository" "taskflow" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.taskflow.arn
  }
}

resource "aws_ecr_lifecycle_policy" "taskflow" {
  repository = aws_ecr_repository.taskflow.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 20 most recently pushed images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_secretsmanager_secret" "application_key" {
  name                    = "${local.name}/application-secret-key"
  description             = "Flask session signing key for TaskFlow"
  kms_key_id              = aws_kms_key.taskflow.arn
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret" "application_database" {
  name                    = "${local.name}/application-database-credentials"
  description             = "Least-privilege PostgreSQL user credentials for TaskFlow"
  kms_key_id              = aws_kms_key.taskflow.arn
  recovery_window_in_days = 7
}

resource "aws_db_subnet_group" "taskflow" {
  name       = "${local.name}-database"
  subnet_ids = aws_subnet.private[*].id
  tags       = { Name = "${local.name}-database" }
}

resource "aws_db_instance" "taskflow" {
  identifier                      = "${local.name}-db"
  engine                          = "postgres"
  instance_class                  = var.database_instance_class
  allocated_storage               = 20
  max_allocated_storage           = 100
  storage_type                    = "gp3"
  storage_encrypted               = true
  kms_key_id                      = aws_kms_key.taskflow.arn
  db_name                         = var.database_name
  username                        = var.database_username
  manage_master_user_password     = true
  master_user_secret_kms_key_id   = aws_kms_key.taskflow.arn
  port                            = 5432
  db_subnet_group_name            = aws_db_subnet_group.taskflow.name
  vpc_security_group_ids          = [aws_security_group.database.id]
  publicly_accessible             = false
  multi_az                        = var.database_multi_az
  backup_retention_period         = 14
  copy_tags_to_snapshot           = true
  deletion_protection             = true
  skip_final_snapshot             = false
  final_snapshot_identifier       = "${local.name}-final"
  auto_minor_version_upgrade      = true
  apply_immediately               = false
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  tags = { Backup = "true" }
}

resource "aws_cloudwatch_log_group" "application" {
  name              = "/ecs/${local.name}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "vpc_flow_logs" {
  name              = "/aws/vpc/flowlogs/${local.name}"
  retention_in_days = 30
}

resource "aws_iam_role" "vpc_flow_logs" {
  name = "${local.name}-vpc-flow-logs"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "vpc-flow-logs.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "vpc_flow_logs" {
  name = "${local.name}-write-vpc-flow-logs"
  role = aws_iam_role.vpc_flow_logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams"
      ]
      Resource = "${aws_cloudwatch_log_group.vpc_flow_logs.arn}:*"
    }]
  })
}

resource "aws_flow_log" "taskflow" {
  vpc_id                   = aws_vpc.taskflow.id
  traffic_type             = "ALL"
  log_destination_type     = "cloud-watch-logs"
  log_destination          = aws_cloudwatch_log_group.vpc_flow_logs.arn
  iam_role_arn             = aws_iam_role.vpc_flow_logs.arn
  max_aggregation_interval = 60
}

resource "aws_ecs_cluster" "taskflow" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_iam_role" "task_execution" {
  name = "${local.name}-task-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "task_secrets" {
  name = "${local.name}-read-runtime-secrets"
  role = aws_iam_role.task_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.application_key.arn, aws_secretsmanager_secret.application_database.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = [aws_kms_key.taskflow.arn]
      }
    ]
  })
}

resource "aws_ecs_task_definition" "taskflow" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn

  volume {
    name = "taskflow-uploads"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.taskflow.id
      transit_encryption = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.taskflow_uploads.id
        iam             = "DISABLED"
      }
    }
  }

  container_definitions = jsonencode([{
    name      = local.name
    image     = "${aws_ecr_repository.taskflow.repository_url}:${var.image_tag}"
    essential = true
    portMappings = [{
      containerPort = 5000
      hostPort      = 5000
      protocol      = "tcp"
    }]
    mountPoints = [{
      sourceVolume  = "taskflow-uploads"
      containerPath = "/app/instance/uploads"
      readOnly      = false
    }]
    environment = [
      { name = "TASKFLOW_COOKIE_SECURE", value = "true" },
      { name = "TASKFLOW_PUBLIC_URL", value = "https://${var.app_domain}" },
      { name = "TASKFLOW_DB_HOST", value = aws_db_instance.taskflow.address },
      { name = "TASKFLOW_DB_PORT", value = "5432" },
      { name = "TASKFLOW_DB_NAME", value = var.database_name }
    ]
    secrets = [
      {
        name      = "TASKFLOW_SECRET_KEY"
        valueFrom = aws_secretsmanager_secret.application_key.arn
      },
      {
        name      = "TASKFLOW_DB_USER"
        valueFrom = "${aws_secretsmanager_secret.application_database.arn}:username::"
      },
      {
        name      = "TASKFLOW_DB_PASSWORD"
        valueFrom = "${aws_secretsmanager_secret.application_database.arn}:password::"
      }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.application.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "taskflow"
      }
    }
    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=3)\" || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
  }])
}

resource "aws_lb" "taskflow" {
  name                       = "${local.name}-alb"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.load_balancer.id]
  subnets                    = aws_subnet.public[*].id
  enable_deletion_protection = true
}

resource "aws_route53_record" "taskflow" {
  count   = var.hosted_zone_id == "" ? 0 : 1
  zone_id = var.hosted_zone_id
  name    = var.app_domain
  type    = "A"

  alias {
    name                   = aws_lb.taskflow.dns_name
    zone_id                = aws_lb.taskflow.zone_id
    evaluate_target_health = true
  }
}

resource "aws_lb_target_group" "taskflow" {
  name        = "${local.name}-app"
  port        = 5000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.taskflow.id

  health_check {
    enabled             = true
    path                = "/api/health"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.taskflow.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.taskflow.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.taskflow.arn
  }
}

resource "aws_ecs_service" "taskflow" {
  name                              = local.name
  cluster                           = aws_ecs_cluster.taskflow.id
  task_definition                   = aws_ecs_task_definition.taskflow.arn
  desired_count                     = var.desired_count
  launch_type                       = "FARGATE"
  health_check_grace_period_seconds = 90
  enable_execute_command            = false

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.application.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.taskflow.arn
    container_name   = local.name
    container_port   = 5000
  }

  depends_on = [aws_lb_listener.https, aws_efs_mount_target.taskflow]
}

resource "aws_sns_topic" "alerts" {
  name              = "${local.name}-alerts"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_event_rule" "backup_failures" {
  name        = "${local.name}-backup-failures"
  description = "Notify when an AWS Backup job for TaskFlow fails or expires."
  event_pattern = jsonencode({
    source      = ["aws.backup"]
    detail-type = ["Backup Job State Change"]
    detail = {
      state = ["FAILED", "ABORTED", "EXPIRED"]
    }
  })
}

resource "aws_sns_topic_policy" "backup_events" {
  arn = aws_sns_topic.alerts.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowBackupFailureEvents"
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sns:Publish"
      Resource  = aws_sns_topic.alerts.arn
      Condition = {
        ArnEquals = {
          "aws:SourceArn" = aws_cloudwatch_event_rule.backup_failures.arn
        }
      }
    }]
  })
}

resource "aws_cloudwatch_event_target" "backup_failures" {
  rule      = aws_cloudwatch_event_rule.backup_failures.name
  target_id = "${local.name}-alerts"
  arn       = aws_sns_topic.alerts.arn
}

resource "aws_cloudwatch_metric_alarm" "ecs_cpu" {
  alarm_name          = "${local.name}-ecs-cpu-high"
  alarm_description   = "Average ECS service CPU utilization exceeded 80% for 10 minutes."
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 80
  comparison_operator = "GreaterThanOrEqualToThreshold"
  dimensions = {
    ClusterName = aws_ecs_cluster.taskflow.name
    ServiceName = aws_ecs_service.taskflow.name
  }
  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${local.name}-alb-5xx"
  alarm_description   = "Application load balancer returned at least five 5xx responses in five minutes."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_ELB_5XX_Count"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  dimensions          = { LoadBalancer = aws_lb.taskflow.arn_suffix }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_log_metric_filter" "application_warnings" {
  name           = "${local.name}-application-warnings"
  log_group_name = aws_cloudwatch_log_group.application.name
  pattern        = "WARNING"

  metric_transformation {
    name      = "ApplicationWarnings"
    namespace = "${local.name}/Application"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "application_warnings" {
  alarm_name          = "${local.name}-application-warnings"
  alarm_description   = "At least five application warning log events were emitted in five minutes."
  namespace           = "${local.name}/Application"
  metric_name         = "ApplicationWarnings"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.application_warnings]
}

resource "aws_cloudwatch_metric_alarm" "target_response_time" {
  alarm_name          = "${local.name}-target-response-time-high"
  alarm_description   = "The 90th percentile application response time exceeded two seconds for ten minutes."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  extended_statistic  = "p90"
  period              = 300
  evaluation_periods  = 2
  threshold           = 2
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    LoadBalancer = aws_lb.taskflow.arn_suffix
    TargetGroup  = aws_lb_target_group.taskflow.arn_suffix
  }
  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "database_cpu" {
  alarm_name          = "${local.name}-database-cpu-high"
  alarm_description   = "RDS database CPU utilization exceeded 80% for 10 minutes."
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 80
  comparison_operator = "GreaterThanOrEqualToThreshold"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.taskflow.identifier }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "database_storage" {
  alarm_name          = "${local.name}-database-storage-low"
  alarm_description   = "RDS free storage fell below 2 GiB."
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 2147483648
  comparison_operator = "LessThanThreshold"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.taskflow.identifier }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_backup_vault" "taskflow" {
  name        = "${local.name}-vault"
  kms_key_arn = aws_kms_key.taskflow.arn
}

resource "aws_backup_plan" "taskflow" {
  name = "${local.name}-daily"

  rule {
    rule_name         = "${local.name}-daily-database"
    target_vault_name = aws_backup_vault.taskflow.name
    schedule          = "cron(0 5 * * ? *)"
    start_window      = 60
    completion_window = 180

    lifecycle {
      delete_after = 35
    }
  }
}

resource "aws_iam_role" "backup" {
  name = "${local.name}-backup"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "backup.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "backup" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}

resource "aws_backup_selection" "taskflow" {
  name         = "${local.name}-database"
  iam_role_arn = aws_iam_role.backup.arn
  plan_id      = aws_backup_plan.taskflow.id

  selection_tag {
    type  = "STRINGEQUALS"
    key   = "Backup"
    value = "true"
  }
}

resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
  client_id_list = [
    "sts.amazonaws.com"
  ]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

resource "aws_iam_role" "github_deploy" {
  name = "${local.name}-github-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = local.github_subject
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_deploy" {
  name = "${local.name}-github-ecr-ecs-deploy"
  role = aws_iam_role.github_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:CompleteLayerUpload",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart"
        ]
        Resource = aws_ecr_repository.taskflow.arn
      },
      {
        Effect = "Allow"
        Action = [
          "ecs:DescribeTaskDefinition",
          "ecs:RegisterTaskDefinition"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecs:DescribeServices",
          "ecs:UpdateService"
        ]
        Resource = aws_ecs_service.taskflow.id
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.task_execution.arn]
      }
    ]
  })
}
